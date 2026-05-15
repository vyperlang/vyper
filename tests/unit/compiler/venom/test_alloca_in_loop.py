"""
Unit tests for alloca behavior in loop CFGs.

These tests pin down the current (static) alloca-in-loop invariants before
dynamic-alloca support is added. They exercise the three cooperating parts
of the pipeline:

1. MemLivenessAnalysis — extends an alloca's live range across loop
   back-edges via its fixpoint propagation, so allocas used in a loop body
   are live for the entire loop.
2. ConcretizeMemLocPass + MemoryAllocator — must NOT reuse a slot between
   two allocas both live in the same loop, but MAY reuse it between
   disjoint branches within a loop, and between allocas whose lifetimes
   are disjoint with respect to the loop.
3. Mem2Var + MakeSSA — a loop-body mload/mstore pair on a 32-byte alloca
   is promoted to SSA, and MakeSSA then inserts the expected loop-header
   phi for the loop-carried value.

The direct test coverage for these cases was previously limited to
incidental functional tests; see tests/functional/codegen/features/
test_alloca_loop_param_init.py (PR #4840 regression). These unit-level
tests catch regressions in the analysis layer itself.
"""

from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import ConcretizeMemLocPass, MakeSSA
from vyper.venom.passes.mem2var import Mem2Var


def _concretize(pre: str):
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    ConcretizeMemLocPass(ac, fn).run_pass()
    return ctx, fn


def _positions_by_var(ctx):
    """Map alloca output variable name -> concrete offset."""
    allocator = ctx.mem_allocator
    result = {}
    for alloca, pos in allocator.allocated.items():
        name = alloca.inst.output.value
        result[name] = pos
    return result


# --------------------------------------------------------------------------
# MemLivenessAnalysis + ConcretizeMemLocPass: slot reuse under loops
# --------------------------------------------------------------------------


def test_two_allocas_in_same_loop_body_no_overlap():
    """
    Two allocas are both accessed inside the same loop body. The liveness
    fixpoint propagates across the back-edge, so both allocas are live for
    the entire loop body — they must NOT share a memory slot.
    """
    pre = """
    main:
        %buf_a = alloca 32
        %buf_b = alloca 32
        jmp @loop_header
    loop_header:
        %i = source
        %cond = iszero %i
        jnz %cond, @exit, @loop_body
    loop_body:
        mstore %buf_a, 11
        mstore %buf_b, 22
        %va = mload %buf_a
        %vb = mload %buf_b
        jmp @loop_header
    exit:
        sink %va, %vb
    """
    ctx, _ = _concretize(pre)

    positions = _positions_by_var(ctx)
    assert (
        positions["%buf_a"] != positions["%buf_b"]
    ), f"two allocas in the same loop body must not share a slot: {positions}"


def test_alloca_defined_before_loop_used_in_loop():
    """
    An alloca defined before the loop and accessed inside the loop must
    be live for the entire loop. Another alloca whose lifetime is strictly
    after the loop can reuse the slot.
    """
    pre = """
    main:
        %loop_buf = alloca 64
        jmp @loop_header
    loop_header:
        %i = source
        %cond = iszero %i
        jnz %cond, @after_loop, @loop_body
    loop_body:
        calldatacopy %loop_buf, 0, 64
        %v = mload %loop_buf
        jmp @loop_header
    after_loop:
        %post_buf = alloca 64
        calldatacopy %post_buf, 100, 64
        %w = mload %post_buf
        sink %v, %w
    """
    ctx, _ = _concretize(pre)

    positions = _positions_by_var(ctx)
    # %loop_buf is only used in the loop, %post_buf only after — their
    # live ranges should be disjoint, so they can share the same slot.
    assert (
        positions["%loop_buf"] == positions["%post_buf"]
    ), f"allocas with disjoint lifetimes should share a slot: {positions}"


def test_allocas_in_disjoint_branches_within_loop():
    """
    Two allocas on mutually exclusive branches inside a loop can still
    share a slot — their live ranges don't overlap at any instruction,
    even after the back-edge propagates liveness.

    This is the loop analog of the existing test_venom_allocation_branches
    test in test_concretize_mem.py.
    """
    pre = """
    main:
        jmp @loop_header
    loop_header:
        %cond = source
        jnz %cond, @then, @else
    then:
        %buf_t = alloca 32
        calldatacopy %buf_t, 0, 32
        %vt = mload %buf_t
        jmp @join
    else:
        %buf_e = alloca 32
        calldatacopy %buf_e, 100, 32
        %ve = mload %buf_e
        jmp @join
    join:
        %done = source
        jnz %done, @exit, @loop_header
    exit:
        stop
    """
    ctx, _ = _concretize(pre)

    positions = _positions_by_var(ctx)
    assert (
        positions["%buf_t"] == positions["%buf_e"]
    ), f"allocas on disjoint branches within a loop should share: {positions}"


def test_alloca_in_nested_loops_no_overlap():
    """
    Two allocas, each accessed in its own nested loop, must not share
    a slot when the inner loop runs inside the outer loop's body (so the
    outer alloca is live across the entire inner loop via the fixpoint).
    """
    pre = """
    main:
        %outer_buf = alloca 32
        %inner_buf = alloca 32
        jmp @outer_header
    outer_header:
        %o = source
        %oc = iszero %o
        jnz %oc, @exit, @outer_body
    outer_body:
        mstore %outer_buf, 1
        jmp @inner_header
    inner_header:
        %i = source
        %ic = iszero %i
        jnz %ic, @outer_tail, @inner_body
    inner_body:
        mstore %inner_buf, 2
        %iv = mload %inner_buf
        jmp @inner_header
    outer_tail:
        %ov = mload %outer_buf
        jmp @outer_header
    exit:
        stop
    """
    ctx, _ = _concretize(pre)

    positions = _positions_by_var(ctx)
    assert (
        positions["%outer_buf"] != positions["%inner_buf"]
    ), f"nested-loop allocas whose live ranges overlap must not share: {positions}"


def test_trivial_self_loop_alloca_liveness():
    """
    A self-looping basic block containing an alloca access still has the
    alloca marked live everywhere in the loop. The fixpoint must converge
    on the self-edge.
    """
    pre = """
    main:
        %buf = alloca 32
        jmp @loop
    loop:
        mstore %buf, 7
        %v = mload %buf
        %cond = source
        jnz %cond, @loop, @exit
    exit:
        sink %v
    """
    ctx, _ = _concretize(pre)

    # Single alloca, it should be at position 0.
    positions = _positions_by_var(ctx)
    assert positions == {"%buf": 0}, positions


# --------------------------------------------------------------------------
# Mem2Var + MakeSSA: loop-carried value via promoted alloca
# --------------------------------------------------------------------------


def _count_opcodes(fn, opcode):
    return sum(
        1 for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == opcode
    )


def _find_insts(fn, opcode):
    return [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == opcode
    ]


def test_mem2var_promotes_alloca_with_loop_body_access():
    """
    A 32-byte alloca whose entire use-set is mload/mstore inside a loop
    body is promoted to SSA by Mem2Var. The subsequent MakeSSA pass must
    then insert a phi node at the loop header for the loop-carried value.

    Mem2Var itself is loop-unaware — the test verifies the cooperation
    between Mem2Var (which mechanically rewrites memory ops to assigns)
    and MakeSSA (which inserts the necessary phis).
    """
    pre = """
    main:
        %ptr = alloca 32
        mstore %ptr, 0
        jmp @loop
    loop:
        %cur = mload %ptr
        %next = add %cur, 1
        mstore %ptr, %next
        %cond = source
        jnz %cond, @loop, @exit
    exit:
        %final = mload %ptr
        sink %final
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)

    # Mem2Var is run in an SSA sandwich: MakeSSA → Mem2Var → MakeSSA.
    MakeSSA(ac, fn).run_pass()
    Mem2Var(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()

    # After the sandwich, every mload and mstore on the promoted alloca
    # should be gone (the alloca has no remaining memory uses).
    assert (
        _count_opcodes(fn, "mload") == 0
    ), "mem2var should have removed all mloads on the promoted alloca"
    assert (
        _count_opcodes(fn, "mstore") == 0
    ), "mem2var should have removed all mstores on the promoted alloca"

    # MakeSSA must insert a phi at the loop header for the loop-carried
    # value. There is exactly one loop in this CFG and one loop-carried
    # value, so exactly one phi is expected.
    phis = _find_insts(fn, "phi")
    assert len(phis) == 1, f"expected exactly one phi, got {len(phis)}: {phis}"

    # The phi must live in the @loop block (the loop header).
    loop_bb = next(bb for bb in fn.get_basic_blocks() if bb.label.value == "loop")
    assert (
        phis[0].parent is loop_bb
    ), f"phi should be at the loop header, found in {phis[0].parent.label}"


def test_mem2var_skips_alloca_with_non_memory_use():
    """
    Mem2Var must NOT promote an alloca whose pointer escapes to a non
    mload/mstore/return use, even if the alloca is inside a loop. Here
    calldatacopy uses the pointer, which is not in mem2var's accepted
    opcode set.
    """
    pre = """
    main:
        %ptr = alloca 32
        jmp @loop
    loop:
        mstore %ptr, 42
        calldatacopy %ptr, 0, 32
        %v = mload %ptr
        %cond = source
        jnz %cond, @loop, @exit
    exit:
        sink %v
    """

    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)

    MakeSSA(ac, fn).run_pass()
    Mem2Var(ac, fn).run_pass()
    MakeSSA(ac, fn).run_pass()

    # The alloca must survive — its pointer is used by calldatacopy,
    # which is not in mem2var's accepted opcode set.
    allocas = _find_insts(fn, "alloca")
    assert len(allocas) == 1, f"alloca should be preserved, got {allocas}"
    # The mload/mstore should also survive since promotion was skipped.
    assert _count_opcodes(fn, "mload") >= 1
    assert _count_opcodes(fn, "mstore") >= 1
