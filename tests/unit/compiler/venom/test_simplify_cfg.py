import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import SimplifyCFGPass

pytestmark = pytest.mark.hevm


_check_pre_post = PrePostChecker(SimplifyCFGPass)


def test_phi_reduction_after_block_pruning():
    pre = """
    _global:
        jmp @then
    then:
        %1 = param
        jmp @join
    else:
        # dead code
        %2 = param
        jmp @join
    join:
        %3 = phi @then, %1, @else, %2
        sink %3
    """
    post = """
    _global:
        %1 = param
        %3 = %1
        sink %3
    """

    _check_pre_post(pre, post)
