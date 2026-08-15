"""
Unit tests for MemLivenessAnalysis.
"""

from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache, MemLivenessAnalysis
from vyper.venom.memory_location import Allocation


def _analyze(pre: str):
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    mem_liveness = ac.request_analysis(MemLivenessAnalysis)
    return fn, mem_liveness


def _find_inst(fn, predicate):
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if predicate(inst):
                return inst
    raise AssertionError("instruction not found")


def _alloca_by_var(fn, name):
    inst = _find_inst(fn, lambda i: i.opcode == "alloca" and i.output.value == name)
    return Allocation(inst)


def test_may_write_through_phi_does_not_kill_liveness():
    """
    BasePtrAnalysis is a may-analysis: a phi-derived pointer resolves to
    multiple candidate allocas. A full-size store through such a pointer
    may write either alloca, so it must NOT kill liveness for any of them.

    Here, killing %a's liveness at `mstore %p, 2` would make %a look dead
    between `mstore %a, 1` and `mload %a`, allowing the allocator to
    overlap %a with another buffer in that gap.
    """
    pre = """
    main:
        %a = alloca 32
        %b = alloca 32
        %cond = source
        mstore %a, 1
        jnz %cond, @left, @right
    left:
        jmp @join
    right:
        jmp @join
    join:
        %p = phi @left, %a, @right, %b
        mstore %p, 2
        %v = mload %a
        sink %v
    """
    fn, mem_liveness = _analyze(pre)

    alloc_a = _alloca_by_var(fn, "%a")
    store_a = _find_inst(fn, lambda i: i.opcode == "mstore" and i.operands[1].value == "%a")

    # %a must stay live across the ambiguous (may-write) store through %p,
    # i.e. it is live at the earlier definite store to %a.
    assert alloc_a in mem_liveness.liveat[store_a], (
        "may-write through a phi-derived pointer must not kill liveness "
        f"of candidate alloca %a: {mem_liveness.liveat[store_a]}"
    )


def test_must_write_kills_liveness():
    """
    Sanity check for the kill path: a full-size store through a pointer
    that resolves to exactly one alloca is a must-write and DOES kill
    liveness above it.
    """
    pre = """
    main:
        %a = alloca 32
        %cond = source
        mstore %a, 1
        mstore %a, 2
        %v = mload %a
        sink %v
    """
    fn, mem_liveness = _analyze(pre)

    alloc_a = _alloca_by_var(fn, "%a")
    first_store = _find_inst(
        fn, lambda i: i.opcode == "mstore" and getattr(i.operands[0], "value", None) == 1
    )

    # the second (full-size, must-write) store kills %a's liveness, so %a
    # is not live at the first store.
    assert alloc_a not in mem_liveness.liveat[first_store], mem_liveness.liveat[first_store]
