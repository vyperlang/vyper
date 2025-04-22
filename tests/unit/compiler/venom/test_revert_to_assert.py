import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import RevertToAssert, SimplifyCFGPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker(passes=[RevertToAssert, SimplifyCFGPass])


def _check_no_change(pre):
    _check_pre_post(pre, pre, hevm=False)


def test_revert_to_assert():
    pre = """
    main:
        %cond = param
        jnz %cond, @revert_block, @else
    revert_block:
        revert 0, 0
    else:
        stop
    """
    post = """
    main:
        %cond = param
        %1 = iszero %cond
        assert %1
        stop
    """
    _check_pre_post(pre, post)


# same test but with branches flipped
def test_revert_to_assert2():
    pre = """
    main:
        %cond = param
        jnz %cond, @then, @revert_block
    then:
        stop
    revert_block:
        revert 0, 0
    """
    post = """
    main:
        %cond = param
        assert %cond
        stop
    """
    _check_pre_post(pre, post)
