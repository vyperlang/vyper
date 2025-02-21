import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import SCCP, SimplifyCFGPass

pytestmark = pytest.mark.hevm


_check_pre_post = PrePostChecker(SCCP, SimplifyCFGPass)


def test_phi_reduction_after_block_pruning():
    pre = """
    _global:
        jnz 1, @then, @else
    then:
        %1 = 1
        jmp @join
    else:
        %2 = 2
        jmp @join
    join:
        %3 = phi @then, %1, @else, %2
        stop
    """
    post = """
    _global:
        %1 = 1
        %3 = %1
        stop
    """

    _check_pre_post(pre, post)
