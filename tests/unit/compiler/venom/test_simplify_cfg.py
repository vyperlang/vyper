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
    main:
        %p = param
        %cond = iszero %p
        jnz %cond, @then, @else
    then:
        %1 = 5
        jmp @then_continue
    then_continue:
        jmp @after
    else:
        %2 = 10
        jmp @else_continue
    else_continue:
        jmp @after
    after:
        %res = phi @else_continue, %2, @then_continue, %1
        sink %res
    """

    post = """
    main:
        %p = param
        %cond = iszero %p
        jnz %cond, @then, @else
    then:
        %1 = 5
        jmp @after
    else:
        %2 = 10
        jmp @after
    after:
        %res = phi @else, %2, @then, %1
        sink %res
    """

    _check_pre_post(pre, post)
