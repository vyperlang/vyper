import pytest
from pyrevm import EVM, AccountInfo

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.evm.address_space import MEMORY
from vyper.evm.assembler.core import assembly_to_evm
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.effects import Effects
from vyper.venom.parser import parse_venom
from vyper.venom.passes import ConcretizeMemLocPass, DallocaSaveRestore
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.load_elimination import LoadElimination
from vyper.venom.venom_to_assembly import VenomCompiler


def _run_cse(pre: str):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        CSE(IRAnalysesCache(fn), fn).run_pass()
    return ctx


def test_dalloca_effects_are_memory_only():
    ctx = parse_from_basic_block(
        """
        main:
            %p = dalloca 32
            sink %p
        """
    )
    fn = next(iter(ctx.functions.values()))
    inst = fn.entry.instructions[0]

    assert Effects.MEMORY in inst.get_read_effects()
    assert Effects.MEMORY_SIZE not in inst.get_read_effects()
    assert Effects.MEMORY in inst.get_write_effects()
    assert Effects.MEMORY_SIZE not in inst.get_write_effects()


def test_cse_does_not_merge_memtop_across_dalloca():
    # dalloca writes MEMORY (the FMP slot); memtop reads MEMORY. The
    # coarse effect-based alias model conservatively prevents CSE'ing
    # the two memtops across the dalloca.
    ctx = _run_cse(
        """
        main:
            %before = memtop
            %dyn = dalloca 32
            %after = memtop
            sink %before, %after, %dyn
        """
    )
    fn = next(iter(ctx.functions.values()))
    memtops = [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == "memtop"
    ]

    assert len(memtops) == 2


def test_cse_does_not_merge_repeated_dalloca():
    ctx = _run_cse(
        """
        main:
            %a = dalloca 32
            %b = dalloca 32
            sink %a, %b
        """
    )
    fn = next(iter(ctx.functions.values()))
    dallocas = [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == "dalloca"
    ]

    assert len(dallocas) == 2


def test_dalloca_does_not_crash_memory_dse():
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
    [
        (b"", 96, 96),
        (b"x", 96, 128),
        (b"x" * 31, 96, 128),
        (b"x" * 32, 96, 128),
        (b"x" * 33, 96, 160),
    ],
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
    [(b"", 96), (b"x", 128), (b"x" * 31, 128), (b"x" * 32, 128), (b"x" * 33, 160)],
)
def test_dalloca_starts_above_static_frame(calldata, expected_ptr2):
    # The static alloca occupies positions 0..64. fn_eom includes the FMP
    # slot at 64..96, so the first dalloca starts at 96 regardless of the
    # static alloca size (as long as it fits below the FMP slot).
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

    assert ptr1 == 96
    assert ptr2 == expected_ptr2


def test_dalloca_static_frame_prime_is_word_aligned():
    # A static alloca of 33 bytes forces fn_eom to be word-aligned above
    # 33; combined with the FMP slot, initial FMP is at least 96.
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

    assert ptr1 == 96
    assert ptr2 == 96


def test_dalloca_rejects_fixed_stack_spills():
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
                %v15 = mload 480
                %v16 = mload 512
                %v17 = mload 544
                %v18 = mload 576
                %v19 = mload 608
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
                %acc15 = add %acc14, %v15
                %acc16 = add %acc15, %v16
                %acc17 = add %acc16, %v17
                %acc18 = add %acc17, %v18
                %acc19 = add %acc18, %v19
                mstore 0, %acc19
                return 0, 32
        }
        """
    )
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()

    with pytest.raises(CompilerPanic, match="Stack spilling is disabled"):
        VenomCompiler(ctx).generate_evm_assembly()


def test_dalloca_pessimizes_load_elimination():
    # dalloca writes MEMORY (the FMP slot) which LoadElimination treats
    # as "writes anywhere". Mloads across dalloca are conservatively not
    # forwarded. This is a pessimization but correctness-preserving.
    pre = """
    main:
        %ptr = alloca 32
        mstore %ptr, 7
        %a = mload %ptr
        %dyn = dalloca 32
        %b = mload %ptr
        sink %a, %b, %dyn
    """
    post = """
    main:
        %ptr = alloca 32
        mstore %ptr, 7
        %a = 7
        %dyn = dalloca 32
        %b = mload %ptr
        sink %a, %b, %dyn
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    LoadElimination(IRAnalysesCache(fn), fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def test_dalloca_allocations_do_not_alias_each_other():
    # dalloca's MEMORY write effect conservatively clears the mload
    # lattice, so LoadElimination does not forward %x. The test here
    # documents that the IR is left unchanged in this pessimistic case.
    pre = """
    main:
        %a = dalloca 32
        mstore %a, 1
        %b = dalloca 32
        mstore %b, 2
        %x = mload %a
        sink %x, %a, %b
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    LoadElimination(IRAnalysesCache(fn), fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(pre))


def _run_program(pre: str, calldata: bytes) -> bytes:
    ctx = parse_venom(pre)
    # ConcretizeMemLocPass requires that callees be processed before
    # callers (MemLivenessAnalysis reads the callee's mems_used).
    # Iterate in reverse declaration order, which matches the order in
    # these fixtures (main first, callee second).
    fns = list(ctx.functions.values())
    for fn in reversed(fns):
        ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
        DallocaSaveRestore(IRAnalysesCache(fn), fn).run_pass()
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
    # the same address B just used -- proving FMP was restored.
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
    assert ptr_after == 96


def test_dalloca_fmp_restored_across_nested_calls():
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
