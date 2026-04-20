import pytest
from pyrevm import EVM, AccountInfo

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.evm.address_space import MEMORY
from vyper.evm.assembler.core import assembly_to_evm
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import IRAnalysesCache
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
            %p = dalloca 32
            sink %p
        """
    )
    fn = next(iter(ctx.functions.values()))
    inst = fn.entry.instructions[0]

    assert Effects.MEMORY not in inst.get_read_effects()
    assert Effects.MEMORY not in inst.get_write_effects()
    assert Effects.MEMORY_SIZE not in inst.get_read_effects()
    assert Effects.MEMORY_SIZE not in inst.get_write_effects()


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
    assert Effects.MEMORY_SIZE not in inst.get_read_effects()
    assert Effects.MEMORY_SIZE not in inst.get_write_effects()


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
            %p = dalloca 32
            mstore %p, 1
            stop
        """
    )
    fn = next(iter(ctx.functions.values()))

    DeadStoreElimination(IRAnalysesCache(fn), fn).run_pass(addr_space=MEMORY)


def _run_probe(pre: str, calldata: bytes) -> tuple[int, int]:
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    # MakeSSA renames fmp reassignments into distinct SSA versions and
    # inserts phis at merge points; required for correct codegen.
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
    out = evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)

    return int.from_bytes(out[:32], "big"), int.from_bytes(out[32:], "big")


@pytest.mark.parametrize(
    ("calldata", "expected_ptr1", "expected_ptr2"),
    [(b"", 64, 64), (b"x", 64, 96), (b"x" * 31, 64, 96), (b"x" * 32, 64, 96), (b"x" * 33, 64, 128)],
)
def test_dalloca_handles_small_sizes(calldata, expected_ptr1, expected_ptr2):
    # Run two back-to-back dallocas and assert the second pointer equals
    # the first plus ceil32(size). This verifies the FMP advance math.
    ptr1, ptr2 = _run_probe(
        """
        main:
            %size = calldatasize
            %a = dalloca %size
            %b = dalloca 32
            mstore 0, %a
            mstore 32, %b
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
    # Initial FMP = max(fn_eom, RESERVED_MEMORY) = 64.
    ptr1, ptr2 = _run_probe(
        """
        main:
            %static = alloca 64
            mstore %static, 0x1111
            %size = calldatasize
            %a = dalloca %size
            %b = dalloca 32
            mstore 0, %a
            mstore 32, %b
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
    # initial FMP is ceil32(max(33, RESERVED_MEMORY=64)) = 64.
    ptr1, ptr2 = _run_probe(
        """
        main:
            %static = alloca 33
            mstore %static, 0x1111
            %a = dalloca 0
            %b = dalloca 32
            mstore 0, %a
            mstore 32, %b
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
                %dyn = dalloca %size
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
    # After DallocaLoweringPass runs, no `dalloca` instruction should
    # remain anywhere in the function.
    ctx = parse_from_basic_block(
        """
        main:
            %size = calldatasize
            %a = dalloca %size
            %b = dalloca 32
            sink %a, %b
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    # Expect bumps in their place (one per dalloca).
    assert opcodes.count("bump") == 2


def test_dalloca_reaching_codegen_panics():
    # Codegen guards against a misconfigured pipeline: if DallocaLoweringPass
    # did not run, any surviving `dalloca` must panic rather than silently
    # produce wrong bytecode.
    ctx = parse_venom(
        """
        function main {
            main:
                %p = dalloca 32
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
    # DallocaLoweringPass also requires callee-first order so that
    # `_needs_fmp` is propagated transitively from callees to callers.
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()
        # MakeSSA renames fmp reassignments into distinct SSA versions
        # and inserts phis at merge points; required for correct
        # codegen.
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
    return evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)


def test_dalloca_memory_reclaimed_across_call():
    # A calls B; B dallocas and returns. After B returns, A dallocas at
    # the same address B just used -- proving the caller's FMP was
    # preserved across the invoke.
    out = _run_program(
        """
        function main {
            main:
                invoke @callee
                %p = dalloca 32
                mstore 0, %p
                return 0, 32
        }

        function callee {
            callee:
                %retpc = param
                %b = dalloca 32
                ret %retpc
        }
        """,
        b"",
    )
    ptr_after = int.from_bytes(out[:32], "big")
    # After the invoke returns, FMP should be restored. The first dalloca
    # in main should land at the same address the callee's dalloca used.
    assert ptr_after == 64


def test_dalloca_fmp_preserved_across_nested_calls():
    # main dallocas, calls f (which dallocas and calls g which also
    # dallocas). After the nested invokes unwind, main dallocas again
    # and that pointer should sit directly above the first dalloca
    # (proving the nested frames were reclaimed).
    out = _run_program(
        """
        function main {
            main:
                %p0 = dalloca 32
                invoke @f
                %p1 = dalloca 32
                mstore 0, %p0
                mstore 32, %p1
                return 0, 64
        }

        function f {
            f:
                %retpc = param
                %a = dalloca 64
                invoke @g
                ret %retpc
        }

        function g {
            g:
                %retpc = param
                %b = dalloca 128
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
                %dyn = dalloca %size
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
                return 0, 32
        }
        """,
        b"",
    )
    # sum of mloads at offsets 0..448 -- all zero for empty calldata --
    # plus dyn pointer. dyn is the initial FMP (64) since calldatasize
    # is 0, so we expect 64.
    assert int.from_bytes(out[:32], "big") == 64


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
                %a = dalloca 64
                jmp @after
            else:
                %b = dalloca 32
                jmp @after
            after:
                %c = dalloca 32
                mstore 0, %c
                return 0, 32
        }
        """,
        b"x",
    )
    # then branch: %a=64, fmp->128; after: %c=128
    ptr = int.from_bytes(out[:32], "big")
    assert ptr == 128


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
