import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import TailMergePass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([TailMergePass])


def _check_no_change(pre: str, hevm: bool = True):
    _check_pre_post(pre, pre, hevm=hevm)


def test_merge_identical_revert_blocks():
    pre = """
    main:
        %cond = source
        jnz %cond, @revert_a, @revert_b
    revert_a:
        revert 0, 0
    revert_b:
        revert 0, 0
    """
    post = """
    main:
        %cond = source
        jnz %cond, @revert_a, @revert_a
    revert_a:
        revert 0, 0
    """

    _check_pre_post(pre, post)


def test_merge_renamed_local_terminal_blocks():
    pre = """
    main:
        %cond = source
        jnz %cond, @a, @b
    a:
        %a0 = 1
        %a1 = add %a0, 2
        revert 0, 0
    b:
        %b0 = 1
        %b1 = add %b0, 2
        revert 0, 0
    """
    post = """
    main:
        %cond = source
        jnz %cond, @a, @a
    a:
        %a0 = 1
        %a1 = add %a0, 2
        revert 0, 0
    """

    _check_pre_post(pre, post)


def test_no_merge_when_block_uses_live_ins():
    pre = """
    main:
        %cond = source
        %x = source
        %y = source
        jnz %cond, @a, @b
    a:
        assert %x
        revert 0, 0
    b:
        assert %y
        revert 0, 0
    """

    _check_no_change(pre)


def test_no_merge_for_non_halting_blocks():
    pre = """
    main:
        %cond = source
        jnz %cond, @a, @b
    a:
        %a = 1
        jmp @join
    b:
        %b = 1
        jmp @join
    join:
        stop
    """

    _check_no_change(pre)


def test_merge_identical_stop_blocks():
    pre = """
    main:
        %cond = source
        jnz %cond, @a, @b
    a:
        stop
    b:
        stop
    """
    post = """
    main:
        %cond = source
        jnz %cond, @a, @a
    a:
        stop
    """

    _check_pre_post(pre, post)


def test_merge_identical_return_blocks():
    pre = """
    main:
        %cond = source
        jnz %cond, @a, @b
    a:
        %a0 = 0
        %a1 = 32
        return %a0, %a1
    b:
        %b0 = 0
        %b1 = 32
        return %b0, %b1
    """
    post = """
    main:
        %cond = source
        jnz %cond, @a, @a
    a:
        %a0 = 0
        %a1 = 32
        return %a0, %a1
    """

    _check_pre_post(pre, post)


def test_no_merge_different_halting_opcodes():
    pre = """
    main:
        %cond = source
        jnz %cond, @a, @b
    a:
        revert 0, 0
    b:
        stop
    """

    _check_no_change(pre)


def test_merge_three_identical_blocks():
    pre = """
    main:
        %c1 = source
        jnz %c1, @block_a, @dispatch
    dispatch:
        %c2 = source
        jnz %c2, @block_b, @block_c
    block_a:
        revert 0, 0
    block_b:
        revert 0, 0
    block_c:
        revert 0, 0
    """
    post = """
    main:
        %c1 = source
        jnz %c1, @block_a, @dispatch
    dispatch:
        %c2 = source
        jnz %c2, @block_a, @block_a
    block_a:
        revert 0, 0
    """

    _check_pre_post(pre, post)


def test_no_merge_entry_block():
    pre = """
    main:
        stop
    other:
        stop
    """

    _check_no_change(pre)


def test_no_merge_with_phi_nodes():
    pre = """
    main:
        %cond = source
        jnz %cond, @left, @right
    left:
        %y = 2
        jnz %cond, @phi_revert, @plain_revert
    right:
        %z = 3
        jnz %cond, @phi_revert, @plain_revert
    phi_revert:
        %p = phi @left, %y, @right, %z
        revert 0, 0
    plain_revert:
        revert 0, 0
    """

    _check_no_change(pre)
