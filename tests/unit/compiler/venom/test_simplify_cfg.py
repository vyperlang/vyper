import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import SimplifyCFGPass

pytestmark = pytest.mark.hevm


_check_pre_post = PrePostChecker([SimplifyCFGPass])


def _check_no_change(pre: str, hevm: bool = True):
    _check_pre_post(pre, pre, hevm=hevm)


def test_phi_reduction_after_block_pruning():
    pre = """
    _global:
        jmp @then
    then:
        %1 = source
        jmp @join
    else:
        ; dead block
        %2 = source
        jmp @join
    join:
        %3 = phi @then, %1, @else, %2
        sink %3
    """
    post = """
    _global:
        %1 = source
        %3 = %1
        sink %3
    """

    _check_pre_post(pre, post)


def test_block_merging():
    """
    demonstrate merging of basic blocks (even if they occur "out of order"
    in the function)
    """
    pre = """
    _global:
        %1 = source
        %2 = source
        jmp @b
    a:
        ; demonstrate order of basic blocks
        %3 = %1
        sstore 0, %3
        jmp @c
    b:
        %4 = %2
        sstore 1, %4
        jmp @a
    c:
        sink %3, %4
    """
    post = """
    _global:
        %1 = source
        %2 = source
        %4 = %2
        sstore 1, %4
        %3 = %1
        sstore 0, %3
        sink %3, %4
    """

    _check_pre_post(pre, post)


def test_phi_after_merge_jump():
    pre = """
    ; this is prelude to get the
    ; condition that would trigger
    ; fixing of the phis in the
    ; _merge_jump method
    main:
        %p = param
        jnz %p, @a, @b
    a:
        mstore %p, %p
        jmp @start
    b:
        mstore %p, %p
        jmp @start
    start:
        %cond = iszero %p
        %1 = 5
        jnz %cond, @then, @else
    then:
        jmp @after ; this jump will be merged in the start block
    else:
        %2 = 10
        jmp @else_continue
    else_continue:
        jmp @after
    after:
        %res = phi @else_continue, %2, @then, %1 ; this phi must be correctly fixed
        sink %res
    """

    post = """
    main:
        %p = param
        jnz %p, @a, @b
    a:
        mstore %p, %p
        jmp @start
    b:
        mstore %p, %p
        jmp @start
    start:
        %cond = iszero %p
        %1 = 5
        jnz %cond, @after, @else
    else:
        %2 = 10
        jmp @after
    after:
        %res = phi @else, %2, @start, %1
        sink %res
    """

    _check_pre_post(pre, post)


def test_merge_jump_other_successor_has_phi():
    """
    Regression test: _merge_jump iterates ALL successors of block `a` to update
    phis, but only the bypassed block's target should have its phi updated.
    Other successors may have phis that don't contain the bypassed block's label,
    causing ValueError from index().

    CFG:
        _global -> entry, other_source
        entry -> passthrough, branched
        other_source -> branched
        passthrough -> join
        branched -> join

    When entry's passthrough is bypassed, entry's successors become {branched, join}.
    The loop incorrectly tries to update phis in `branched`, which has @entry and
    @other_source but NOT @passthrough.
    """
    pre = """
    _global:
        %cond = source
        jnz %cond, @entry, @other_source

    entry:
        jnz %cond, @passthrough, @branched

    other_source:
        jmp @branched

    passthrough:
        jmp @join

    branched:
        %x = phi @entry, %cond, @other_source, %cond
        jmp @join

    join:
        %y = phi @passthrough, %cond, @branched, %x
        sink %y
    """

    # After optimization:
    # - other_source bypassed, _global jumps directly to branched
    # - passthrough bypassed, entry jumps directly to join
    # - phis updated accordingly
    post = """
    _global:
        %cond = source
        jnz %cond, @entry, @branched

    entry:
        jnz %cond, @join, @branched

    branched:
        %x = phi @entry, %cond, @_global, %cond
        jmp @join

    join:
        %y = phi @entry, %cond, @branched, %x
        sink %y
    """

    _check_pre_post(pre, post)


def test_merge_jump_target_has_no_phi():
    """
    Regression test: bypassing a jump should not touch phis in unrelated successors,
    even when the target block has no phi.
    """
    pre = """
    _global:
        %cond = source
        jnz %cond, @entry, @other_source

    entry:
        jnz %cond, @passthrough, @branched

    other_source:
        jmp @branched

    passthrough:
        jmp @join

    branched:
        %x = phi @entry, %cond, @other_source, %cond
        jmp @join

    join:
        sink %cond
    """

    post = """
    _global:
        %cond = source
        jnz %cond, @entry, @branched

    entry:
        jnz %cond, @join, @branched

    branched:
        %x = phi @entry, %cond, @_global, %cond
        jmp @join

    join:
        sink %cond
    """

    _check_pre_post(pre, post)


def test_merge_jump_dedup_phi_when_direct_edge():
    """
    If the bypassed block's target is already a successor, avoid duplicating phi labels.
    """
    pre = """
    _global:
        %cond = source
        jnz %cond, @entry, @other

    entry:
        %x = source
        jnz %cond, @passthrough, @join

    other:
        %o = source
        jmp @join

    passthrough:
        jmp @join

    join:
        %y = phi @entry, %x, @passthrough, %x, @other, %o
        sink %y
    """

    post = """
    _global:
        %cond = source
        jnz %cond, @entry, @other

    entry:
        %x = source
        jnz %cond, @join, @join

    other:
        %o = source
        jmp @join

    join:
        %y = phi @entry, %x, @other, %o
        sink %y
    """

    _check_pre_post(pre, post, hevm=False)


def test_merge_jump_conflicting_phi_operands():
    """
    Skip merging when the same predecessor would imply different phi operands.
    """
    pre = """
    _global:
        %cond = source
        jnz %cond, @entry, @other

    entry:
        %x = source
        %y = source
        jnz %cond, @passthrough, @join

    other:
        %o = source
        jmp @join

    passthrough:
        jmp @join

    join:
        %z = phi @entry, %x, @passthrough, %y, @other, %o
        sink %z
    """

    _check_no_change(pre, hevm=False)
