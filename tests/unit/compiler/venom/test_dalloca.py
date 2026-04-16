from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.evm.address_space import MEMORY
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.effects import Effects
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.load_elimination import LoadElimination


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
