import pytest
from pyrevm import AccountInfo, EVM

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.evm.assembler.core import assembly_to_evm
from vyper.evm.address_space import MEMORY
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.parser import parse_venom
from vyper.venom.effects import Effects
from vyper.venom.passes import ConcretizeMemLocPass
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.load_elimination import LoadElimination
from vyper.venom.venom_to_assembly import VenomCompiler


def _run_cse(pre: str):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        CSE(IRAnalysesCache(fn), fn).run_pass()
    return ctx


def test_dalloca_effects_track_memory_size_without_content_write():
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
    assert Effects.MEMORY_SIZE in inst.get_read_effects()
    assert Effects.MEMORY not in inst.get_write_effects()
    assert Effects.MEMORY_SIZE in inst.get_write_effects()


def test_cse_does_not_merge_memtop_across_dalloca():
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
    ("calldata", "expected_ptr", "expected_msize"),
    [
        (b"", 32, 32),
        (b"x", 32, 64),
        (b"x" * 31, 32, 64),
        (b"x" * 32, 32, 64),
        (b"x" * 33, 32, 96),
    ],
)
def test_dalloca_handles_small_sizes(calldata, expected_ptr, expected_msize):
    ptr, msize = _run_probe(
        """
        main:
            %size = calldatasize
            %dyn = dalloca %size
            %after = memtop
            mstore 0, %dyn
            mstore 32, %after
            return 0, 64
        """,
        calldata,
    )

    assert ptr == expected_ptr
    assert msize == expected_msize


@pytest.mark.parametrize(
    ("calldata", "expected_msize"),
    [
        (b"", 64),
        (b"x", 96),
        (b"x" * 31, 96),
        (b"x" * 32, 96),
        (b"x" * 33, 128),
    ],
)
def test_dalloca_starts_above_static_frame(calldata, expected_msize):
    ptr, msize = _run_probe(
        """
        main:
            %static = alloca 64
            mstore %static, 0x1111
            %size = calldatasize
            %dyn = dalloca %size
            %after = memtop
            mstore 0, %dyn
            mstore 32, %after
            return 0, 64
        """,
        calldata,
    )

    assert ptr == 64
    assert msize == expected_msize


def test_dalloca_static_frame_prime_is_word_aligned():
    ptr, msize = _run_probe(
        """
        main:
            %static = alloca 33
            mstore %static, 0x1111
            %dyn = dalloca 0
            %after = memtop
            mstore 0, %dyn
            mstore 32, %after
            return 0, 64
        """,
        b"",
    )

    assert ptr == 64
    assert msize == 64


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


def test_dalloca_does_not_invalidate_memory_content_loads():
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
        %b = %a
        sink %a, %b, %dyn
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    LoadElimination(IRAnalysesCache(fn), fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))
