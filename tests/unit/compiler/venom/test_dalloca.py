import pytest
from pyrevm import EVM, AccountInfo

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.evm.address_space import MEMORY
from vyper.evm.assembler.core import assembly_to_evm
from vyper.exceptions import CompilerPanic
from vyper.venom import run_passes_on
from vyper.venom.analysis import (
    IRAnalysesCache,
    LoadAnalysis,
    MemoryAliasAnalysis,
    MemSSA,
    ReadonlyMemoryArgsGlobalAnalysis,
    VarDefinition,
    VariableRangeAnalysis,
)
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.parser import parse_venom
from vyper.venom.passes import (
    ConcretizeMemLocPass,
    DallocaLoweringPass,
    MakeSSA,
    PhiEliminationPass,
)
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.load_elimination import LoadElimination
from vyper.venom.venom_to_assembly import VenomCompiler


def _apply_lowering(fn):
    """Apply the post-dalloca-lowering pass pipeline to a single function.

    Run in callee-first order when there are multiple functions.
    """
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()


def _run_cse(pre: str):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        CSE(IRAnalysesCache(fn), fn).run_pass()
    return ctx


def test_dalloca_has_no_memory_effects():
    # `dalloca` is high-level sugar; it has no memory effects and is
    # lowered away before any effect-sensitive pass runs.
    ctx = parse_from_basic_block(
        """
        main:
            %p, %p_mark = dalloca 32
            sink %p
        """
    )
    fn = next(iter(ctx.functions.values()))
    inst = fn.entry.instructions[0]

    assert Effects.MEMORY not in inst.get_read_effects()
    assert Effects.MEMORY not in inst.get_write_effects()


def test_bump_has_no_memory_effects():
    # `bump` is pure arithmetic — no memory effects.
    # Textual convention: textual leftmost is TOS. For output (a, a+b)
    # with stack `[a, b]` (b TOS), the textual form is `bump b, a`.
    ctx = parse_from_basic_block(
        """
        main:
            %fmp = calldatasize
            %p, %new_fmp = bump 32, %fmp
            sink %p, %new_fmp
        """
    )
    fn = next(iter(ctx.functions.values()))
    inst = fn.entry.instructions[1]

    assert Effects.MEMORY not in inst.get_read_effects()
    assert Effects.MEMORY not in inst.get_write_effects()


def test_cse_does_not_merge_repeated_bump():
    # Two `bump`s with identical operands are allocation-distinct at
    # runtime (the FMP dataflow chain makes the operands differ in
    # practice, but even if they matched textually, they must not be
    # merged). CSE excludes multi-output instructions; the non-idempotent
    # flag is the additional belt-and-suspenders guard.
    ctx = _run_cse(
        """
        main:
            %fmp = calldatasize
            %a, %f1 = bump 32, %fmp
            %b, %f2 = bump 32, %fmp
            sink %a, %b, %f1, %f2
        """
    )
    fn = next(iter(ctx.functions.values()))
    bumps = [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == "bump"
    ]

    assert len(bumps) == 2


def test_dalloca_does_not_crash_memory_dse():
    # Pre-lowering: DSE sees `dalloca` with no effects and must not
    # crash on it (even though the shape is meaningless).
    ctx = parse_from_basic_block(
        """
        main:
            %p, %p_mark = dalloca 32
            mstore %p, 1
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))

    DeadStoreElimination(IRAnalysesCache(fn), fn).run_pass(addr_space=MEMORY)


def _run_probe(pre: str, calldata: bytes) -> tuple[int, int]:
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    _apply_lowering(fn)
    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)

    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    out = evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)

    return int.from_bytes(out[:32], "big"), int.from_bytes(out[32:], "big")


@pytest.mark.parametrize(
    ("calldata", "expected_ptr1", "expected_ptr2"),
    [(b"", 0, 0), (b"x", 0, 32), (b"x" * 31, 0, 32), (b"x" * 32, 0, 32), (b"x" * 33, 0, 64)],
)
def test_dalloca_handles_small_sizes(calldata, expected_ptr1, expected_ptr2):
    # Run two nested dallocas and assert the second pointer equals the
    # first plus ceil32(size). This verifies the FMP advance math.
    # Strict pairing: both dallocas are freed in LIFO order before return.
    ptr1, ptr2 = _run_probe(
        """
        main:
            %size = calldatasize
            %a, %a_mark = dalloca %size
            %b, %b_mark = dalloca 32
            mstore 0, %a
            mstore 32, %b
            dfree %b_mark
            dfree %a_mark
            return 0, 64
        """,
        calldata,
    )

    assert ptr1 == expected_ptr1
    assert ptr2 == expected_ptr2


@pytest.mark.parametrize(
    ("calldata", "expected_ptr2"),
    [(b"", 64), (b"x", 96), (b"x" * 31, 96), (b"x" * 32, 96), (b"x" * 33, 128)],
)
def test_dalloca_starts_above_static_frame(calldata, expected_ptr2):
    # A static alloca of 64 bytes occupies [0, 64); fn_eom = 64.
    # Initial FMP = fn_eom = 64.
    ptr1, ptr2 = _run_probe(
        """
        main:
            %static = alloca 64
            mstore %static, 0x1111
            %size = calldatasize
            %a, %a_mark = dalloca %size
            %b, %b_mark = dalloca 32
            mstore 0, %a
            mstore 32, %b
            dfree %b_mark
            dfree %a_mark
            return 0, 64
        """,
        calldata,
    )

    # Memory layout after the mstores used by dalloca testing:
    # [0..32) and [32..64) are scratch for writing back results.
    # Allocation of %static collides with them, but after the mstores
    # at the end, the returned values at offsets 0/32 are the pointers
    # we care about.
    assert ptr1 == 64
    assert ptr2 == expected_ptr2


def test_dalloca_static_frame_prime_is_word_aligned():
    # A static alloca of 33 bytes forces fn_eom to 33+0 = 33; the
    # initial FMP is ceil32(33) = 64.
    ptr1, ptr2 = _run_probe(
        """
        main:
            %static = alloca 33
            mstore %static, 0x1111
            %a, %a_mark = dalloca 0
            %b, %b_mark = dalloca 32
            mstore 0, %a
            mstore 32, %b
            dfree %b_mark
            dfree %a_mark
            return 0, 64
        """,
        b"",
    )

    assert ptr1 == 64
    assert ptr2 == 64


def test_dalloca_allows_stack_spills():
    # The old memory-slot design forbade spilling for functions that
    # contained dalloca (since spills would collide with the FMP slot).
    # With stack-threaded FMP, spilling is fully compatible: spill slots
    # live above fn_eom (below initial FMP), so they do not alias any
    # live dynamic allocation.
    #
    # This test exercises a function with many live vars across a
    # dalloca to force the spiller to kick in. In the previous design
    # this would raise `CompilerPanic("Stack spilling is disabled ...")`.
    ctx = parse_venom(
        """
        function spill_demo {
            main:
                %v0 = mload 0
                %v1 = mload 32
                %v2 = mload 64
                %v3 = mload 96
                %v4 = mload 128
                %v5 = mload 160
                %v6 = mload 192
                %v7 = mload 224
                %v8 = mload 256
                %v9 = mload 288
                %v10 = mload 320
                %v11 = mload 352
                %v12 = mload 384
                %v13 = mload 416
                %v14 = mload 448
                %size = calldatasize
                %dyn, %dyn_mark = dalloca %size
                %acc0 = add %dyn, %v0
                %acc1 = add %acc0, %v1
                %acc2 = add %acc1, %v2
                %acc3 = add %acc2, %v3
                %acc4 = add %acc3, %v4
                %acc5 = add %acc4, %v5
                %acc6 = add %acc5, %v6
                %acc7 = add %acc6, %v7
                %acc8 = add %acc7, %v8
                %acc9 = add %acc8, %v9
                %acc10 = add %acc9, %v10
                %acc11 = add %acc10, %v11
                %acc12 = add %acc11, %v12
                %acc13 = add %acc12, %v13
                %acc14 = add %acc13, %v14
                mstore 0, %acc14
                dfree %dyn_mark
                return 0, 32
        }
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()

    # Should compile without panicking (stack spilling is now allowed).
    VenomCompiler(ctx).generate_evm_assembly()


def test_bump_does_not_pessimize_load_elimination():
    # `bump` has no memory effects, so LoadElimination can forward
    # mloads across it. Textual `bump b, a` -> outputs (a, a+b).
    pre = """
    main:
        %ptr = alloca 32
        mstore %ptr, 7
        %a = mload %ptr
        %fmp = calldatasize
        %dyn, %new_fmp = bump 32, %fmp
        %b = mload %ptr
        sink %a, %b, %dyn, %new_fmp
    """
    post = """
    main:
        %ptr = alloca 32
        mstore %ptr, 7
        %a = 7
        %fmp = calldatasize
        %dyn, %new_fmp = bump 32, %fmp
        %b = %a
        sink %a, %b, %dyn, %new_fmp
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    LoadElimination(IRAnalysesCache(fn), fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def test_bump_allocations_do_not_alias_each_other():
    # Each `bump` produces a fresh base pointer distinct from every
    # other base. Since `bump` has no memory effects, LoadElimination
    # can forward %x through both mstores.
    pre = """
    main:
        %fmp0 = calldatasize
        %a, %fmp1 = bump 32, %fmp0
        mstore %a, 1
        %b, %fmp2 = bump 32, %fmp1
        mstore %b, 2
        %x = mload %a
        sink %x, %a, %b
    """
    post = """
    main:
        %fmp0 = calldatasize
        %a, %fmp1 = bump 32, %fmp0
        mstore %a, 1
        %b, %fmp2 = bump 32, %fmp1
        mstore %b, 2
        %x = 1
        sink %x, %a, %b
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    LoadElimination(IRAnalysesCache(fn), fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def test_dalloca_is_fully_lowered():
    # After DallocaLoweringPass runs, no `dalloca` or `dfree` remains.
    # Nested-but-paired dallocas go through the FMP-threaded path; the
    # inner pair rewires to the current threaded FMP and the outer
    # restore becomes `assign mark -> fmp`. Result: one bump and no raw
    # dalloca/dfree left in the IR.
    ctx = parse_from_basic_block(
        """
        main:
            %size = calldatasize
            %a, %a_mark = dalloca %size
            %b, %b_mark = dalloca 32
            mstore %a, %b
            dfree %b_mark
            dfree %a_mark
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "dfree" not in opcodes
    assert opcodes.count("bump") == 1
    assert opcodes.count("assign") >= 1


def test_dalloca_alignment_mask_uses_small_literal():
    ctx = parse_from_basic_block(
        """
        main:
            %size = calldatasize
            %p, %mark = dalloca %size
            mstore %p, 1
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "not" and inst.operands == [IRLiteral(31)] for inst in insts)
    assert not any(
        inst.opcode == "and" and any(isinstance(op, IRLiteral) for op in inst.operands)
        for inst in insts
    )


def test_dalloca_lowering_invalidates_stale_analyses():
    ctx = parse_from_basic_block(
        """
        main:
            %size = calldatasize
            %p, %mark = dalloca %size
            mstore %p, 1
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)

    ac.request_analysis(LoadAnalysis)
    ac.request_analysis(MemSSA)
    ac.request_analysis(MemoryAliasAnalysis)
    ac.request_analysis(VarDefinition)
    ac.request_analysis(VariableRangeAnalysis)
    ac.request_analysis(ReadonlyMemoryArgsGlobalAnalysis)

    DallocaLoweringPass(ac, fn).run_pass()

    assert LoadAnalysis not in ac.analyses_cache
    assert MemSSA not in ac.analyses_cache
    assert MemoryAliasAnalysis not in ac.analyses_cache
    assert VarDefinition not in ac.analyses_cache
    assert VariableRangeAnalysis not in ac.analyses_cache
    assert ReadonlyMemoryArgsGlobalAnalysis not in ctx.global_analyses_cache.analyses_cache


def test_dalloca_reaching_codegen_panics():
    # Codegen guards against a misconfigured pipeline: if DallocaLoweringPass
    # did not run, any surviving `dalloca` must panic rather than silently
    # produce wrong bytecode.
    ctx = parse_venom(
        """
        function main {
            main:
                %p, %p_mark = dalloca 32
                mstore 0, %p
                return 0, 32
        }
        """
    )
    with pytest.raises(CompilerPanic, match="dalloca reached codegen"):
        VenomCompiler(ctx).generate_evm_assembly()


def _run_program(pre: str, calldata: bytes) -> bytes:
    ctx = parse_venom(pre)
    # ConcretizeMemLocPass requires that callees be processed before
    # callers (MemLivenessAnalysis reads the callee's mems_used).
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        _apply_lowering(fn)
    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)

    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    return evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)


def _run_program_full_pipeline(
    pre: str, calldata: bytes, *, disable_inlining: bool
) -> tuple[bytes, object]:
    ctx = parse_venom(pre)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=disable_inlining)
    run_passes_on(ctx, flags, disable_mem_checks=True)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)

    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    out = evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)
    return out, ctx


def test_dalloca_memory_reclaimed_across_call():
    # A calls B; B dallocas without dfree (reclaimed implicitly at ret
    # via SSA liveness). After B returns, A dallocas at the same address
    # B used -- caller's FMP was preserved across the invoke.
    out = _run_program(
        """
        function main {
            main:
                invoke @callee
                %p, %p_mark = dalloca 32
                mstore 0, %p
                return 0, 32
        }

        function callee {
            callee:
                %retpc = param
                %b, %b_mark = dalloca 32
                ret %retpc
        }
        """,
        b"",
    )
    ptr_after = int.from_bytes(out[:32], "big")
    assert ptr_after == 0


def test_dalloca_memory_reclaimed_across_call_after_inlining():
    src = """
    function main {
        main:
            invoke @callee
            %p, %p_mark = dalloca 32
            mstore 0, %p
            return 0, 32
    }

    function callee {
        callee:
            %retpc = param
            %b, %b_mark = dalloca 32
            ret %retpc
    }
    """

    out_inlined, ctx_inlined = _run_program_full_pipeline(src, b"", disable_inlining=False)
    out_no_inline, _ = _run_program_full_pipeline(src, b"", disable_inlining=True)

    assert int.from_bytes(out_inlined[:32], "big") == 0
    assert out_inlined == out_no_inline
    assert IRLabel("callee") not in ctx_inlined.functions


def test_inlining_cleanup_removes_dead_entry_fmp_plumbing():
    src = """
    function main {
        main:
            invoke @callee
            stop
    }

    function callee {
        callee:
            %retpc = param
            %p, %mark = dalloca 32
            dfree %mark
            ret %retpc
    }
    """

    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2)
    run_passes_on(ctx, flags, disable_mem_checks=True)

    main = ctx.get_function(IRLabel("main"))
    assert IRLabel("callee") not in ctx.functions
    assert main._needs_fmp is False
    assert all(inst.opcode != "param" for inst in main.entry.instructions)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    assert all("__initial_fmp__" not in str(item) for item in asm)


def test_dead_hidden_fmp_pruning_deduplicates_join_users():
    ctx = parse_venom(
        """
        function main {
            main:
                %fmp = param
                %retpc = param
                %cond = calldatasize
                jnz %cond, @left, @right

            left:
                %left_fmp = assign %fmp
                jmp @join

            right:
                %right_fmp = assign %fmp
                jmp @join

            join:
                %merged_fmp = phi @left, %left_fmp, @right, %right_fmp
                ret %retpc
        }
        """
    )
    fn = ctx.get_function(IRLabel("main"))
    fn._needs_fmp = True

    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "phi" not in opcodes
    assert "assign" not in opcodes
    params = list(fn.entry.param_instructions)
    assert len(params) == 1
    assert params[0].output == IRVariable("%retpc")
    assert fn._needs_fmp is False


def test_stale_fmp_arg_cleanup_removes_only_hidden_fmp_alias():
    ctx = parse_venom(
        """
        function main {
            main:
                %fmp = param
                invoke @callee, %fmp
                stop
        }

        function callee {
            callee:
                %retpc = param
                ret %retpc
        }
        """
    )
    main = ctx.get_function(IRLabel("main"))
    main._needs_fmp = True

    DallocaLoweringPass(IRAnalysesCache(main), main).run_pass()

    invoke = next(
        inst
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    assert len(invoke.operands) == 1
    assert main._needs_fmp is False


def test_stale_fmp_arg_cleanup_keeps_non_fmp_extra_operand():
    ctx = parse_venom(
        """
        function main {
            main:
                %fmp = param
                %arg = source
                invoke @callee, %arg
                stop
        }

        function callee {
            callee:
                %retpc = param
                ret %retpc
        }
        """
    )
    main = ctx.get_function(IRLabel("main"))
    main._needs_fmp = True

    DallocaLoweringPass(IRAnalysesCache(main), main).run_pass()

    invoke = next(
        inst
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    assert invoke.operands[1:] == [IRVariable("%arg")]


def test_dalloca_threads_hidden_fmp_at_tail_of_call_layout():
    ctx = parse_venom(
        """
        function main {
            main:
                %arg = alloca 32
                invoke @callee, %arg
                stop
        }

        function callee {
            callee:
                %arg = param
                %retpc = param
                %p, %mark = dalloca 32
                dfree %mark
                ret %retpc
        }
        """
    )
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    main = ctx.get_function(IRLabel("main"))
    callee = ctx.get_function(IRLabel("callee"))

    invoke = next(
        inst
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    assert invoke.operands[1] == IRVariable("%arg")
    assert invoke.operands[-1] == next(inst.output for inst in main.entry.param_instructions)

    callee_params = [inst.output for inst in callee.entry.param_instructions]
    assert callee_params[0] == IRVariable("%arg")
    assert callee_params[1] != IRVariable("%retpc")
    assert callee_params[-1] == IRVariable("%retpc")


def test_dalloca_fmp_preserved_across_nested_calls():
    # main dallocas, calls f (which dallocas and calls g which also
    # dallocas). After the nested invokes unwind, main dallocas again
    # and that pointer should sit directly above the first dalloca
    # (proving the nested frames were reclaimed).
    out = _run_program(
        """
        function main {
            main:
                %p0, %p0_mark = dalloca 32
                invoke @f
                %p1, %p1_mark = dalloca 32
                mstore 0, %p0
                mstore 32, %p1
                return 0, 64
        }

        function f {
            f:
                %retpc = param
                %a, %a_mark = dalloca 64
                invoke @g
                ret %retpc
        }

        function g {
            g:
                %retpc = param
                %b, %b_mark = dalloca 128
                ret %retpc
        }
        """,
        b"",
    )
    p0 = int.from_bytes(out[:32], "big")
    p1 = int.from_bytes(out[32:64], "big")
    assert p1 == p0 + 32


def test_dalloca_spiller_with_dalloca():
    # Regression test: a function that forces spilling AND contains a
    # dalloca. The stack-threaded design lets both coexist. Verify that
    # the bytecode runs correctly end-to-end.
    out = _run_program(
        """
        function main {
            main:
                %v0 = mload 0
                %v1 = mload 32
                %v2 = mload 64
                %v3 = mload 96
                %v4 = mload 128
                %v5 = mload 160
                %v6 = mload 192
                %v7 = mload 224
                %v8 = mload 256
                %v9 = mload 288
                %v10 = mload 320
                %v11 = mload 352
                %v12 = mload 384
                %v13 = mload 416
                %v14 = mload 448
                %size = calldatasize
                %dyn, %dyn_mark = dalloca %size
                %acc0 = add %dyn, %v0
                %acc1 = add %acc0, %v1
                %acc2 = add %acc1, %v2
                %acc3 = add %acc2, %v3
                %acc4 = add %acc3, %v4
                %acc5 = add %acc4, %v5
                %acc6 = add %acc5, %v6
                %acc7 = add %acc6, %v7
                %acc8 = add %acc7, %v8
                %acc9 = add %acc8, %v9
                %acc10 = add %acc9, %v10
                %acc11 = add %acc10, %v11
                %acc12 = add %acc11, %v12
                %acc13 = add %acc12, %v13
                %acc14 = add %acc13, %v14
                mstore 0, %acc14
                dfree %dyn_mark
                return 0, 32
        }
        """,
        b"",
    )
    # sum of mloads at offsets 0..448 -- all zero for empty calldata --
    # plus dyn pointer. dyn is the initial FMP, which is 0 without static
    # allocations or spills.
    assert int.from_bytes(out[:32], "big") == 0


def test_dalloca_spill_does_not_corrupt_dynamic_allocation():
    # The spiller writes spill slots starting from fn_eom[fn]. The initial
    # FMP baked in at contract entry must account for peak spill usage, not
    # just static frame size; otherwise a function with small fn_eom and
    # heavy stack pressure can have spill slots aliasing with the dalloca
    # region.
    #
    # This test writes a distinctive sentinel to the dalloca-allocated
    # memory, then forces many simultaneously-live variables (enough
    # to push the spiller above fn_eom), then reads back from the
    # dalloca region. If spills corrupt it, the readback won't match
    # the sentinel.
    sentinel = 0xDEADBEEFCAFEBABEFEEDFACE1234567800112233AABBCCDD9988776655443322
    # Force real spilling by passing 20 values into an invoke. Each arg
    # must sit on the EVM stack simultaneously when the invoke JUMPs;
    # exceeding the 16-slot reachable-stack window forces the spiller to
    # write to memory at offsets starting at fn_eom[fn] (= 0 for functions
    # with no static allocas).
    #
    # The initial FMP baked in at contract entry must account for actual
    # peak spill usage, so dalloca's returned pointer stays above spill
    # slots even though the static frame is empty.
    N = 20
    mloads = "\n".join(f"                %v{i} = mload {1024 + i*32}" for i in range(N))
    invoke_args = ", ".join(f"%v{i}" for i in range(N))
    out = _run_program(
        f"""
        function main {{
            main:
                %sz = calldatasize
                %dyn, %dyn_mark = dalloca %sz
                mstore %dyn, {hex(sentinel)}
{mloads}
                %r = invoke @consume, {invoke_args}
                %readback = mload %dyn
                %final = add %r, %readback
                mstore 0, %final
                dfree %dyn_mark
                return 0, 32
        }}

        function consume {{
            consume:
                %a0 = param
                %a1 = param
                %a2 = param
                %a3 = param
                %a4 = param
                %a5 = param
                %a6 = param
                %a7 = param
                %a8 = param
                %a9 = param
                %a10 = param
                %a11 = param
                %a12 = param
                %a13 = param
                %a14 = param
                %a15 = param
                %a16 = param
                %a17 = param
                %a18 = param
                %a19 = param
                %retpc = param
                %s = add %a0, %a1
                ret %retpc, %s
        }}
        """,
        b"",
    )
    # All mloads above address 1024 return 0. consume sums %a0 + %a1 = 0.
    # If the dalloca region is uncorrupted: readback == sentinel, so
    # final == 0 + sentinel. If a spill clobbered the dalloca region,
    # readback is some spilled variable value, and the assertion fails.
    expected = sentinel % (2**256)
    assert int.from_bytes(out[:32], "big") == expected


def test_dalloca_across_branch():
    # dalloca in both branches of a conditional. The merge block uses
    # the advanced FMP via a phi introduced by MakeSSA.
    out = _run_program(
        """
        function main {
            main:
                %cond = calldatasize
                jnz %cond, @then, @else
            then:
                %a, %a_mark = dalloca 64
                jmp @after
            else:
                %b, %b_mark = dalloca 32
                jmp @after
            after:
                %c, %c_mark = dalloca 32
                mstore 0, %c
                return 0, 32
        }
        """,
        b"x",
    )
    # then branch: %a=0, fmp->64; after: %c = initial_fmp + 64.
    ptr = int.from_bytes(out[:32], "big")
    assert ptr == 64


def test_bump_direct_emission():
    # End-to-end: user hand-writes `bump` in Venom (no dalloca sugar),
    # runs MakeSSA (not strictly needed since this is already SSA), and
    # compiles to bytecode. Verifies that the `bump` primitive works
    # standalone. Textual `bump b, a` -> outputs (a, a+b).
    ctx = parse_venom(
        """
        function main {
            main:
                %fmp_init = calldatasize
                %p1, %fmp1 = bump 32, %fmp_init
                %p2, %fmp2 = bump 64, %fmp1
                mstore 0, %p1
                mstore 32, %p2
                return 0, 64
        }
        """
    )
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()
    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)

    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    # Empty calldata => calldatasize == 0, so %fmp_init = 0.
    out = evm.message_call(caller=caller, to=addr, calldata=b"", gas=1_000_000)
    p1 = int.from_bytes(out[:32], "big")
    p2 = int.from_bytes(out[32:], "big")
    assert p1 == 0
    assert p2 == 32


def test_dalloca_asymmetric_branch():
    # Only the `then` branch dallocas; the `else` branch doesn't. At the
    # merge point, the FMP phi must correctly select the advanced fmp
    # from the then branch or the unchanged fmp from the else branch.
    # After merge, a second dalloca must land above both possibilities.
    out = _run_program(
        """
        function main {
            main:
                %cond = calldatasize
                jnz %cond, @then, @else
            then:
                %a, %a_mark = dalloca 64
                jmp @after
            else:
                jmp @after
            after:
                %b, %b_mark = dalloca 32
                mstore 0, %b
                return 0, 32
        }
        """,
        b"x",  # non-empty: then branch
    )
    # then branch: fmp advances by 64, so %b = initial + 64
    assert int.from_bytes(out[:32], "big") == 64

    out = _run_program(
        """
        function main {
            main:
                %cond = calldatasize
                jnz %cond, @then, @else
            then:
                %a, %a_mark = dalloca 64
                jmp @after
            else:
                jmp @after
            after:
                %b, %b_mark = dalloca 32
                mstore 0, %b
                return 0, 32
        }
        """,
        b"",  # empty: else branch
    )
    # else branch: fmp didn't advance, so %b = initial
    assert int.from_bytes(out[:32], "big") == 0


# --------------------------------------------------------------------------
# dfree: scoped FMP reclamation
# --------------------------------------------------------------------------


def test_dfree_initial_fmp_fast_path():
    # Entry leaf function with a paired dalloca/dfree and no invokes takes
    # the initial_fmp fast path. The dalloca mark is materialized as an
    # assign from the pointer, and dfree is dropped.
    ctx = parse_from_basic_block(
        """
        main:
            %p, %mark = dalloca 32
            mstore %p, 7
            dfree %mark
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "dfree" not in opcodes
    assert "bump" not in opcodes
    assert "sub" not in opcodes
    assert opcodes.count("initial_fmp") == 1
    assert opcodes.count("assign") == 1
    assert fn._needs_fmp is False


def test_dfree_restores_from_mark_on_intervening_invoke():
    # With an invoke between dalloca and dfree, rewiring would leave the
    # caller's data at an address that a fast-path callee could clobber.
    # The lowering must keep the bump and restore the threaded FMP from
    # the dalloca mark at the dfree point.
    ctx = parse_venom(
        """
        function main {
            main:
                %p, %mark = dalloca 32
                mstore %p, 7
                invoke @callee
                dfree %mark
                stop
        }

        function callee {
            callee:
                %retpc = param
                %q, %qmark = dalloca 32
                dfree %qmark
                ret %retpc
        }
        """
    )
    # Callee-first lowering.
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    main_fn = ctx.get_function(next(iter(ctx.functions)))
    opcodes = [inst.opcode for bb in main_fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "dfree" not in opcodes
    assert "bump" in opcodes
    assert opcodes.count("assign") >= 2


def test_dfree_without_matching_dalloca_is_low_level_restore():
    # `dfree` is a low-level FMP restore primitive. A standalone dfree is
    # allowed and simply lowers to `assign mark -> fmp`.
    ctx = parse_from_basic_block(
        """
        main:
            %mark = calldatasize
            dfree %mark
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dfree" not in opcodes
    assert fn._needs_fmp is True
    assert opcodes.count("assign") == 1


def test_dfree_non_lifo_marks_lower_without_validation():
    ctx = parse_from_basic_block(
        """
        main:
            %a, %amark = dalloca 32
            %b, %bmark = dalloca 64
            dfree %amark
            dfree %bmark
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dfree" not in opcodes
    assert opcodes.count("bump") == 2
    assert opcodes.count("assign") >= 3


def test_dfree_rewrite_keeps_bump_when_fmp_redefined_output_only():
    ctx = parse_from_basic_block(
        """
        main:
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    bb = fn.entry
    fmp_var = IRVariable("%fmp")
    ptr = IRVariable("%p")
    mark = IRVariable("%mark")
    origin = IRInstruction("dalloca", [IRLiteral(32)], [ptr, mark])
    origin.parent = bb

    pass_ = DallocaLoweringPass(IRAnalysesCache(fn), fn)
    lowered, entry = pass_._lower_dalloca(origin, fn, fmp_var, bb)
    fmp_redefinition = IRInstruction("source", [], [fmp_var])
    fmp_redefinition.parent = bb
    new_instructions = [*lowered, fmp_redefinition]

    dfree = IRInstruction("dfree", [mark], [])
    dfree.parent = bb
    pass_._lower_dfree(dfree, fmp_var, bb, [entry], new_instructions)

    assert entry["bump_inst"] in new_instructions
    assert new_instructions[-1].opcode == "assign"
    assert new_instructions[-1].output == fmp_var


def test_dfree_does_not_do_pointer_lifetime_validation():
    # Pointer lifetime validation is not part of this low-level IR
    # contract; dfree restores the FMP but does not prove pointer safety.
    ctx = parse_from_basic_block(
        """
        main:
            %p, %mark = dalloca 32
            mstore %p, 1
            dfree %mark
            %v = mload %p
            sink %v
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "initial_fmp" not in opcodes
    assert fn._needs_fmp is True


def test_initial_fmp_fast_path_rejects_aliased_use_after_dfree():
    ctx = parse_from_basic_block(
        """
        main:
            %p, %mark = dalloca 32
            %alias = assign %p
            dfree %mark
            %v = mload %alias
            sink %v
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "initial_fmp" not in opcodes
    assert fn._needs_fmp is True


def test_initial_fmp_fast_path_rejects_closed_ptr_live_out_to_phi():
    ctx = parse_from_basic_block(
        """
        main:
            %p, %mark = dalloca 32
            dfree %mark
            %cond = calldatasize
            jnz %cond, @left, @right

        left:
            jmp @join

        right:
            %q = 64
            jmp @join

        join:
            %x = phi @left, %p, @right, %q
            %v = mload %x
            sink %v
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "initial_fmp" not in opcodes
    assert fn._needs_fmp is True


def test_initial_fmp_fast_path_rejects_invoke_during_live_dalloca():
    # Entry-function initial_fmp lowering is disabled when an invoke occurs
    # while a dalloca allocation is live; the function falls back to FMP
    # threading so the callee cannot alias the caller's open scratch.
    ctx = parse_venom(
        """
        function main {
            main:
                %p, %mark = dalloca 32
                mstore %p, 111
                invoke @helper
                dfree %mark
                stop
        }

        function helper {
            helper:
                %retpc = param
                ret %retpc
        }
        """
    )
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    main_fn = ctx.get_function(next(iter(ctx.functions)))
    opcodes = [inst.opcode for bb in main_fn.get_basic_blocks() for inst in bb.instructions]
    assert "initial_fmp" not in opcodes
    assert "bump" in opcodes
    assert main_fn._needs_fmp is True


def test_initial_fmp_fast_path_allows_invoke_between_closed_scratch_pairs():
    ctx = parse_venom(
        """
        function main {
            main:
                %p, %pmark = dalloca 32
                mstore %p, 111
                dfree %pmark
                invoke @helper
                %q, %qmark = dalloca 64
                mstore 0, %q
                dfree %qmark
                return 0, 32
        }

        function helper {
            helper:
                %retpc = param
                ret %retpc
        }
        """
    )
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    main_fn = ctx.get_function(next(iter(ctx.functions)))
    opcodes = [inst.opcode for bb in main_fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "dfree" not in opcodes
    assert "bump" not in opcodes
    assert opcodes.count("initial_fmp") == 2
    assert main_fn._needs_fmp is False


def test_initial_fmp_fast_path_rejects_closed_scratch_around_needs_fmp_callee():
    ctx = parse_venom(
        """
        function main {
            main:
                %p, %pmark = dalloca 32
                mstore %p, 111
                dfree %pmark
                invoke @helper
                stop
        }

        function helper {
            helper:
                %retpc = param
                %q, %qmark = dalloca 32
                mstore %q, 222
                dfree %qmark
                ret %retpc
        }
        """
    )
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    main_fn = ctx.get_function(next(iter(ctx.functions)))
    helper_fn = ctx.get_function(IRLabel("helper", True))
    invoke = next(
        inst
        for bb in main_fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )

    assert "initial_fmp" not in [
        inst.opcode for bb in main_fn.get_basic_blocks() for inst in bb.instructions
    ]
    assert main_fn._needs_fmp is True
    assert helper_fn._needs_fmp is True
    assert len(invoke.operands) == 2


def test_dfree_nested_falls_back_to_fmp_threading():
    # Nested dalloca/dfree pairs cannot share a base address (both are
    # live at the same time), so the initial_fmp fast path is rejected.
    # The pass falls back to FMP threading: inner rewires to the current
    # threaded FMP and outer restore becomes `assign mark -> fmp`.
    ctx = parse_from_basic_block(
        """
        main:
            %a, %amark = dalloca 32
            mstore %a, 1
            %b, %bmark = dalloca 64
            mstore %b, 2
            dfree %bmark
            dfree %amark
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "dfree" not in opcodes
    assert "initial_fmp" not in opcodes
    # Outer bump remains; inner bump is gone via rewire.
    assert opcodes.count("bump") == 1
    assert opcodes.count("assign") >= 3
    assert fn._needs_fmp is True


def test_dfree_initial_fmp_fast_path_runs():
    # End-to-end: leaf function with non-overlapping dalloca+dfree pairs
    # takes the initial_fmp fast path. Both scratches share the same
    # base address (the initial FMP constant); the second write clobbers
    # the first, which is correct because the first was freed.
    out = _run_program(
        """
        function main {
            main:
                %p, %pmark = dalloca 32
                mstore %p, 1
                dfree %pmark
                %q, %qmark = dalloca 64
                mstore 0, %q
                dfree %qmark
                return 0, 32
        }
        """,
        b"",
    )
    ptr = int.from_bytes(out[:32], "big")
    # Both %p and %q resolve to the initial FMP constant (= 0 for this
    # small program with no static frame or spills).
    assert ptr == 0


def test_dfree_fmp_thread_path_reclaims_memory():
    # Exercise the FMP-threading path by having main invoke a needs_fmp
    # helper that itself dallocas and frees. The invoke forces main off
    # the entry-only initial_fmp path. Main's dfree restores the threaded
    # FMP from its mark; %q lands at the freed base of %p.
    out = _run_program(
        """
        function main {
            main:
                %p, %pmark = dalloca 32
                mstore %p, 1
                invoke @needs_fmp_helper
                dfree %pmark
                %q, %qmark = dalloca 64
                mstore 0, %q
                dfree %qmark
                return 0, 32
        }

        function needs_fmp_helper {
            needs_fmp_helper:
                %retpc = param
                %scratch, %scratch_mark = dalloca 16
                dfree %scratch_mark
                ret %retpc
        }
        """,
        b"",
    )
    assert int.from_bytes(out[:32], "big") == 0


def test_cross_bb_dfree_reclaims_threaded_fmp():
    out = _run_program(
        """
        function main {
            main:
                %p, %pmark = dalloca 32
                %cond = calldatasize
                jnz %cond, @left, @right

            left:
                jmp @free

            right:
                jmp @free

            free:
                dfree %pmark
                %q, %qmark = dalloca 32
                mstore 0, %q
                dfree %qmark
                return 0, 32
        }
        """,
        b"",
    )
    assert int.from_bytes(out[:32], "big") == 0


def test_loop_carried_dalloca_threads_fmp():
    out, _ = _run_program_full_pipeline(
        """
        function main {
            main:
                %i = 0
                jmp @loop

            loop:
                %p, %pmark = dalloca 32
                %i = add %i, 1
                %done = eq %i, 2
                jnz %done, @exit, @loop

            exit:
                mstore 0, %p
                return 0, 32
        }
        """,
        b"",
        disable_inlining=True,
    )
    assert int.from_bytes(out[:32], "big") == 32


def test_non_entry_dalloca_uses_threaded_marks_not_initial_fmp():
    ctx = parse_venom(
        """
        function main {
            main:
                %p, %mark = dalloca 32
                mstore %p, 111
                invoke @helper
                dfree %mark
                stop
        }

        function helper {
            helper:
                %retpc = param
                %q, %qmark = dalloca 32
                mstore %q, 39
                dfree %qmark
                ret %retpc
        }
        """
    )
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    helper = ctx.get_function(IRLabel("helper", True))
    helper_opcodes = [inst.opcode for bb in helper.get_basic_blocks() for inst in bb.instructions]
    assert "initial_fmp" not in helper_opcodes
    assert helper._needs_fmp is True
