import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import SimplifyCFGPass

pytestmark = pytest.mark.hevm


_check_pre_post = PrePostChecker([SimplifyCFGPass])


def test_phi_reduction_after_block_pruning():
    pre = """
    _global:
        jmp @then
    then:
        %1 = param
        jmp @join
    else:
        ; dead block
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


def test_block_merging():
    """
    demonstrate merging of basic blocks (even if they occur "out of order"
    in the function)
    """
    pre = """
    _global:
        %1 = param
        %2 = param
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
        %1 = param
        %2 = param
        %4 = %2
        sstore 1, %4
        %3 = %1
        sstore 0, %3
        sink %3, %4
    """

    _check_pre_post(pre, post)
