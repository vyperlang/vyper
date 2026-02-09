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
