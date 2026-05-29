import pytest
from pyrevm import EVM, AccountInfo

from tests.venom_utils import parse_from_basic_block
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.evm.address_space import MEMORY
from vyper.evm.assembler.core import assembly_to_evm
from vyper.exceptions import CompilerPanic
from vyper.venom import run_passes_on
from vyper.venom.analysis import (
    DFGAnalysis,
    IRAnalysesCache,
    LoadAnalysis,
    MemoryAliasAnalysis,
    MemSSA,
    ReadonlyMemoryArgsGlobalAnalysis,
    VarDefinition,
    VariableRangeAnalysis,
)
from vyper.venom.basicblock import IRLabel, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.parser import parse_venom
from vyper.venom.passes import (
    ConcretizeMemLocPass,
    DallocaLoweringPass,
    DretLoweringPass,
    MakeSSA,
    PhiEliminationPass,
)
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.function_inliner import FunctionInlinerPass
from vyper.venom.venom_to_assembly import VenomCompiler


def _run_ssa(fn):
    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()


def _apply_dalloca_lowering(fn):
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    _run_ssa(fn)
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    _run_ssa(fn)


def _apply_lowering(fn):
    DretLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    _apply_dalloca_lowering(fn)


def _run_program(src: str, calldata: bytes = b"") -> bytes:
    ctx = parse_venom(src)
    for fn in reversed(list(ctx.functions.values())):
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
    src: str, calldata: bytes = b"", *, disable_inlining: bool
) -> tuple[bytes, object]:
    ctx = parse_venom(src)
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


def _word(out: bytes, idx: int = 0) -> int:
    return int.from_bytes(out[idx * 32 : (idx + 1) * 32], "big")


def test_dalloca_has_no_memory_effects():
    ctx = parse_from_basic_block("""
        main:
            %p = dalloca 32
            sink %p
        """)
    fn = next(iter(ctx.functions.values()))
    inst = fn.entry.instructions[0]

    assert Effects.MEMORY not in inst.get_read_effects()
    assert Effects.MEMORY not in inst.get_write_effects()


def test_dalloca_does_not_crash_memory_dse():
    ctx = parse_from_basic_block("""
        main:
            %p = dalloca 32
            mstore %p, 1
            stop
        """)
    fn = next(iter(ctx.functions.values()))

    DeadStoreElimination(IRAnalysesCache(fn), fn).run_pass(addr_space=MEMORY)


@pytest.mark.parametrize(
    ("calldata", "expected_ptr1", "expected_ptr2"),
    [(b"", 0, 0), (b"x", 0, 32), (b"x" * 31, 0, 32), (b"x" * 32, 0, 32), (b"x" * 33, 0, 64)],
)
def test_dalloca_handles_small_sizes(calldata, expected_ptr1, expected_ptr2):
    out = _run_program(
        """
        function main {
            main:
                %size = calldatasize
                %a = dalloca %size
                %b = dalloca 32
                mstore 0, %a
                mstore 32, %b
                return 0, 64
        }
        """,
        calldata,
    )

    assert _word(out, 0) == expected_ptr1
    assert _word(out, 1) == expected_ptr2


def test_dalloca_static_frame_prime_is_word_aligned():
    out = _run_program("""
        function main {
            main:
                %static = alloca 33
                mstore %static, 0x1111
                %a = dalloca 0
                %b = dalloca 32
                mstore 0, %a
                mstore 32, %b
                return 0, 64
        }
        """)

    assert _word(out, 0) == 64
    assert _word(out, 1) == 64


def test_dalloca_is_fully_lowered():
    ctx = parse_from_basic_block("""
        main:
            %size = calldatasize
            %a = dalloca %size
            %b = dalloca 32
            mstore %a, %b
            stop
    """)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    _run_ssa(fn)
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "bump" in opcodes


def test_dalloca_alignment_mask_uses_small_literal():
    ctx = parse_from_basic_block("""
        main:
            %size = calldatasize
            %p = dalloca %size
            mstore %p, 1
            stop
    """)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    _run_ssa(fn)
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "not" and inst.operands == [IRLiteral(31)] for inst in insts)
    assert not any(
        inst.opcode == "and" and any(isinstance(op, IRLiteral) for op in inst.operands)
        for inst in insts
    )


def test_dalloca_lowering_invalidates_stale_analyses():
    ctx = parse_from_basic_block("""
        main:
            %size = calldatasize
            %p = dalloca %size
            mstore %p, 1
            stop
        """)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    _run_ssa(fn)

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
    ctx = parse_venom("""
        function main {
            main:
                %p = dalloca 32
                mstore 0, %p
                return 0, 32
        }
        """)
    with pytest.raises(CompilerPanic, match="dalloca reached codegen"):
        VenomCompiler(ctx).generate_evm_assembly()


def test_dret_reaching_codegen_panics():
    ctx = parse_venom("""
        function main {
            main:
                %retpc = param
                %p = 0
                dret 1, %p, 32, %retpc
        }
        """)
    with pytest.raises(CompilerPanic, match="dret reached codegen"):
        VenomCompiler(ctx).generate_evm_assembly()


def test_auto_reclaim_before_later_allocation_when_dead():
    out = _run_program("""
        function main {
            main:
                %p = dalloca 32
                mstore %p, 7
                %q = dalloca 32
                mstore 0, %q
                return 0, 32
        }
        """)
    assert _word(out) == 0


def test_auto_reclaim_keeps_aliased_live_allocation():
    out = _run_program("""
        function main {
            main:
                %p = dalloca 32
                %alias = %p
                mstore %p, 7
                %q = dalloca 32
                %v = mload %alias
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """)
    assert _word(out, 0) == 32
    assert _word(out, 1) == 7


def test_auto_reclaim_keeps_pointer_arithmetic_alias_live():
    out = _run_program("""
        function main {
            main:
                %p = dalloca 64
                %q = add 32, %p
                mstore %q, 7
                %r = dalloca 64
                %r_tail = add 32, %r
                mstore %r_tail, 9
                %v = mload %q
                mstore 0, %r
                mstore 32, %v
                return 0, 64
        }
        """)
    assert _word(out, 0) == 64
    assert _word(out, 1) == 7


def test_auto_reclaim_pre_ssa_reassigned_pointer_var_is_conservative():
    out = _run_program(
        """
        function main {
            main:
                %zero = 0
                %p = dalloca 64
                %d = add 32, %p
                mstore %d, 7
                %cond = calldatasize
                jnz %cond, @clobber, @keep

            keep:
                jmp @join

            clobber:
                %d = %zero
                jmp @join

            join:
                %q = dalloca 64
                %q_tail = add 32, %q
                mstore %q_tail, 0xdead
                %v = mload %d
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """,
        b"",
    )
    assert _word(out, 0) == 64
    assert _word(out, 1) == 7


def test_auto_reclaim_only_dead_lifo_suffix():
    out = _run_program("""
        function main {
            main:
                %a = dalloca 32
                %b = dalloca 32
                mstore %a, 1
                %c = dalloca 32
                mstore %b, 1
                mstore 0, %c
                return 0, 32
        }
        """)
    assert _word(out) == 64


def test_auto_reclaim_across_simple_branches():
    out = _run_program(
        """
        function main {
            main:
                %p = dalloca 32
                %cond = calldatasize
                jnz %cond, @left, @right

            left:
                mstore %p, 11
                jmp @join

            right:
                mstore %p, 22
                jmp @join

            join:
                %q = dalloca 32
                mstore 0, %q
                return 0, 32
        }
        """,
        b"x",
    )
    assert _word(out) == 0


def test_loop_carried_dalloca_threads_fmp_conservatively():
    out, _ = _run_program_full_pipeline(
        """
        function main {
            main:
                %i = 0
                jmp @loop

            loop:
                %p = dalloca 32
                %i = add %i, 1
                %done = eq %i, 2
                jnz %done, @exit, @loop

            exit:
                mstore 0, %p
                return 0, 32
        }
        """,
        disable_inlining=True,
    )
    assert _word(out) == 32


def test_hidden_fmp_output_on_dret_invoke_moves_later_dalloca():
    out = _run_program("""
        function main {
            main:
                %returned = invoke @callee
                %next = dalloca 32
                mstore 0, %returned
                mstore 32, %next
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                mstore %p, 7
                dret 1, %p, 32, %retpc
        }
        """)
    assert _word(out, 0) == 0
    assert _word(out, 1) == 32


def test_stale_hidden_fmp_arg_removed_after_callee_prunes_fmp():
    out, ctx = _run_program_full_pipeline(
        """
        function main {
            main:
                %p = dalloca 32
                mstore %p, 5
                invoke @callee
                %v = mload %p
                mstore 0, %v
                return 0, 32
        }

        function callee {
            callee:
                %retpc = param
                %q = dalloca 32
                ret %retpc
        }
        """,
        disable_inlining=True,
    )

    assert _word(out) == 5

    callee = ctx.get_function(IRLabel("callee"))
    assert not callee._needs_fmp

    main = ctx.get_function(IRLabel("main"))
    invoke = next(
        inst
        for bb in main.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    assert invoke.operands == [IRLabel("callee")]


def test_stale_hidden_fmp_cleanup_keeps_non_fmp_extra_arg():
    ctx = parse_venom("""
        function caller {
            caller:
                %fmp = param
                %arg = source
                mstore 0, %fmp
                invoke @callee, %arg
                stop
        }

        function callee {
            callee:
                %retpc = param
                ret %retpc
        }
        """)

    caller = ctx.get_function(IRLabel("caller"))
    caller._needs_fmp = True
    DallocaLoweringPass(IRAnalysesCache(caller), caller).run_pass()

    invoke = next(
        inst
        for bb in caller.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "invoke"
    )
    assert invoke.operands == [IRLabel("callee"), IRVariable("%arg")]


def test_no_ret_function_inserts_hidden_fmp_before_return_pc():
    # An internal function that unconditionally terminates (no `ret`/`dret`,
    # e.g. reverts, self-destructs) still carries a return-PC param. When it needs FMP
    # (here, a dalloca), the hidden FMP param must be inserted *before* the
    # return-PC param and the bump must thread that FMP — not reuse the
    # return-PC value as the allocation base. Regression for layout inference
    # counting a not-yet-inserted hidden FMP slot.
    ctx = parse_venom("""
        function f {
            f:
                %a = param
                %retpc = param
                %p = dalloca 64
                mstore %p, %a
                return %p, 64
        }
        """)

    fn = ctx.get_function(IRLabel("f"))
    fn._invoke_param_count = 1  # one user param (%a); %retpc is the return-PC param

    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    params = [inst for inst in fn.entry.instructions if inst.opcode == "param"]
    # a hidden FMP param was inserted (user, hidden_fmp, return_pc)
    assert len(params) == 3
    retpc = IRVariable("%retpc")
    # return-PC param stays last; the inserted hidden FMP sits before it
    assert params[-1].output == retpc
    hidden_fmp = params[1].output
    assert hidden_fmp != retpc

    bump = next(
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == "bump"
    )

    # resolve the bump's FMP operand through any assign chain back to its root
    defs = {
        inst.output: inst
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.num_outputs == 1
    }
    root = bump.operands[0]
    while isinstance(root, IRVariable) and root in defs and defs[root].opcode == "assign":
        root = defs[root].operands[0]

    # the FMP base must be the inserted hidden FMP param, never the return PC
    assert root == hidden_fmp
    assert root != retpc


def test_get_transitive_uses_handles_multi_output_bump():
    # Regression: DFGAnalysis.get_transitive_uses walked only `.output`, which
    # asserts a single output. `bump` (the lowered form of `dalloca`) has two
    # outputs, so taking transitive uses of a bump must not crash.
    ctx = parse_venom("""
        function main {
            main:
                %p = dalloca 64
                %q = add 32, %p
                mstore %q, 7
                return %p, 64
        }
        """)
    fn = ctx.get_function(IRLabel("main"))
    _apply_lowering(fn)

    bump = next(
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == "bump"
    )

    dfg = IRAnalysesCache(fn).request_analysis(DFGAnalysis)
    uses = dfg.get_transitive_uses(bump)  # must not raise on the 2-output bump

    assert bump in uses
    # the pointer output feeds `add %q`, reachable transitively from the bump
    assert any(inst.opcode == "add" for inst in uses)


def test_dret_lowering_with_ordinary_return_and_dynamic_buffer():
    out = _run_program("""
        function main {
            main:
                %ordinary, %ptr = invoke @callee
                %v = mload %ptr
                mstore 0, %ordinary
                mstore 32, %v
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                mstore %p, 0x1234
                dret 1, 99, %p, 32, %retpc
        }
        """)
    assert _word(out, 0) == 99
    assert _word(out, 1) == 0x1234


def test_dret_lowering_with_multiple_dynamic_buffers():
    out = _run_program("""
        function main {
            main:
                %a, %b = invoke @callee
                %va = mload %a
                %vb = mload %b
                mstore 0, %a
                mstore 32, %b
                mstore 64, %va
                mstore 96, %vb
                return 0, 128
        }

        function callee {
            callee:
                %retpc = param
                %a = dalloca 32
                %b = dalloca 32
                mstore %a, 11
                mstore %b, 22
                dret 2, %a, 32, %b, 32, %retpc
        }
        """)
    assert _word(out, 0) == 0
    assert _word(out, 1) == 32
    assert _word(out, 2) == 11
    assert _word(out, 3) == 22


def test_dret_bad_return_order_can_clobber_later_source():
    out = _run_program("""
        function main {
            main:
                %a, %b = invoke @callee
                %va = mload %a
                %vb = mload %b
                mstore 0, %va
                mstore 32, %vb
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %a = dalloca 32
                %b = dalloca 32
                mstore %a, 11
                mstore %b, 22
                dret 2, %b, 32, %a, 32, %retpc
        }
        """)
    assert _word(out, 0) == 22
    assert _word(out, 1) == 22


@pytest.mark.parametrize(("calldata", "expected_next"), [(b"", 0), (b"x" * 33, 64)])
def test_dret_supports_zero_and_runtime_sizes(calldata, expected_next):
    out = _run_program(
        """
        function main {
            main:
                %returned = invoke @callee
                %next = dalloca 32
                mstore 0, %returned
                mstore 32, %next
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %size = calldatasize
                %p = dalloca 64
                mstore %p, 7
                dret 1, %p, %size, %retpc
        }
        """,
        calldata,
    )
    assert _word(out, 0) == 0
    assert _word(out, 1) == expected_next


def test_dret_pre_cancun_copy_path(monkeypatch):
    import vyper.venom.passes.dalloca_lowering as dalloca_lowering

    monkeypatch.setattr(dalloca_lowering, "version_check", lambda **kwargs: False)
    ctx = parse_venom("""
        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
    """)
    fn = ctx.get_function(IRLabel("callee"))
    DretLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "mcopy" not in opcodes
    assert "staticcall" in opcodes
    assert "assert" in opcodes


def test_dret_full_pipeline_with_and_without_inlining():
    src = """
    function main {
        main:
            %ptr = invoke @callee
            %v = mload %ptr
            mstore 0, %v
            return 0, 32
    }

    function callee {
        callee:
            %retpc = param
            %p = dalloca 32
            mstore %p, 123
            dret 1, %p, 32, %retpc
    }
    """

    out_inlined, ctx_inlined = _run_program_full_pipeline(src, disable_inlining=False)
    out_no_inline, _ = _run_program_full_pipeline(src, disable_inlining=True)

    assert _word(out_inlined) == 123
    assert out_inlined == out_no_inline
    assert IRLabel("callee") not in ctx_inlined.functions


def test_dret_adopted_fmp_flows_to_later_non_inlined_callee():
    out, _ = _run_program_full_pipeline(
        """
        function main {
            main:
                %ptr = invoke @producer
                jmp @join

            join:
                invoke @scratch
                %v = mload %ptr
                mstore 0, %v
                return 0, 32
        }

        function producer {
            producer:
                %retpc = param
                %p = dalloca 32
                mstore %p, 0x1234
                dret 1, %p, 32, %retpc
        }

        function scratch {
            scratch:
                %retpc = param
                %q = dalloca 32
                mstore %q, 0xdead
                ret %retpc
        }
        """,
        disable_inlining=True,
    )

    assert _word(out) == 0x1234


def test_unreachable_raw_dret_does_not_block_inlining():
    ctx = parse_venom("""
        function main {
            main:
                return 0, 0
        }

        function dead {
            dead:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
        """)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=False)

    run_passes_on(ctx, flags, disable_mem_checks=True)

    assert IRLabel("dead") not in ctx.functions


def test_dret_must_be_lowered_before_inlining():
    ctx = parse_venom("""
        function main {
            main:
                %ptr = invoke @callee
                sink %ptr
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
        """)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    with pytest.raises(CompilerPanic, match="DretLoweringPass must run before"):
        FunctionInlinerPass(analyses, ctx, VenomOptimizationFlags()).run_pass()
