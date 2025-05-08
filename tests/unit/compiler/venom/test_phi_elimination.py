import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import PhiEliminationPass

_check_pre_post = PrePostChecker([PhiEliminationPass], default_hevm=False)


@pytest.mark.hevm
def test_simple_phi_elimination():
    pre = """
    main:
        %1 = param
        %cond = param
        %2 = %1
        jnz %cond, @then, @else
    then:
        jmp @else
    else:
        %3 = phi @main, %1, @else, %2
        sink %3
    """

    post = """
    main:
        %1 = param
        %cond = param
        %2 = %1
        jnz %cond, @then, @else
    then:
        jmp @else
    else:
        %3 = %1
        sink %3
    """

    _check_pre_post(pre, post, hevm=True)


def test_phi_elim_loop_tmp():
    pre = """
    main:
        %v = param
        jmp @loop
    loop:
        %v:2 = phi @main, %v, @loop, %v:2
        jmp @loop
    """

    post = """
    main:
        %v = param
        jmp @loop
    loop:
        %v:2 = %v
        jmp @loop
    """

    _check_pre_post(pre, post)


def test_phi_elim_loop2():
    pre = """
    main:
        %1 = calldataload 0
        %2 = %1
        jmp @condition

    condition:
        %3 = phi @main, %1, @body, %4
        %cond = calldataload 100
        jnz %cond, @exit, @body

    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %another_cond, @condition, @exit

    exit:
        %5 = phi @condition, %3, @body, %4
        mstore 0, %5
        return 0, 32
    """

    post = """
    main:
        %1 = calldataload 0
        %2 = %1
        jmp @condition

    condition:
        %3 = %1
        %cond = calldataload 100
        jnz %cond, @exit, @body

    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %another_cond, @condition, @exit

    exit:
        %5 = %1
        mstore 0, %5
        return 0, 32
    """

    _check_pre_post(pre, post)


def test_phi_elim_loop_inner_phi():
    pre = """
    main:
        %1 = param
        %rand = param
        %2 = %1
        jmp @condition
    condition:
        %3 = phi @main, %1, @body, %6
        %cond = iszero %3
        jnz %cond, @exit, @body
    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %rand, @then, @else
    then:
        %6:1 = %4
        jmp @join
    else:
        %6:2 = %1
        jmp @join
    join:
        %6 = phi @then, %6:1, @else, %6:2
        jnz %another_cond, @condition, @exit
    exit:
        %5 = phi @condition, %3, @body, %4
        sink %5
    """

    post = """
    main:
        %1 = param
        %rand = param
        %2 = %1
        jmp @condition
    condition:
        %3 = %1
        %cond = iszero %3
        jnz %cond, @exit, @body
    body:
        %4 = %2
        %another_cond = calldataload 200
        jnz %rand, @then, @else
    then:
        %6:1 = %4
        jmp @join
    else:
        %6:2 = %1
        jmp @join
    join:
        %6 = %1
        jnz %another_cond, @condition, @exit
    exit:
        %5 = %1
        sink %5
    """

    _check_pre_post(pre, post)


def test_phi_elim_loop_inner_phi_simple():
    pre = """
    main:
        %p = param
        jmp @loop_start
    loop_start:
        %1 = phi @main, %p, @loop_join, %4
        jnz %1, @then, @else
    then:
        %2 = %1
        jmp @loop_join
    else:
        %3 = %1
        jmp @loop_join
    loop_join:
        %4 = phi @then, %2, @else, %3
        jmp @loop_start
    """

    post = """
    main:
        %p = param
        jmp @loop_start
    loop_start:
        %1 = %p
        jnz %1, @then, @else
    then:
        %2 = %1
        jmp @loop_join
    else:
        %3 = %1
        jmp @loop_join
    loop_join:
        %4 = %p
        jmp @loop_start
    """

    _check_pre_post(pre, post)


def test_phi_elim_cannot_remove():
    pre = """
    main:
        %p = param
        %rand = param
        jmp @cond
    cond:
        %1 = phi @main, %p, @body, %3
        %cond = iszero %1
        jnz %cond, @body, @join
    body:
        jnz %rand, @then, @join
    then:
        %2 = 2
        jmp @join
    join:
        %3 = phi @body, %1, @then, %2
        jmp @cond
    exit:
        sink %p
    """

    _check_pre_post(pre, pre, hevm=False)


def test_phi_elim_direct_loop():
    pre1 = """
    main:
        %p = param
        jmp @loop
    loop:
        %1 = phi @main, %p, @loop, %2
        %2 = %1
        jmp @loop
    """

    pre2 = """
    main:
        %p = param
        jmp @loop
    loop:
        %1 = phi @main, %p, @loop, %2
        %2 = %1
        jmp @loop
    """

    post = """
    main:
        %p = param
        jmp @loop
    loop:
        %1 = %p
        %2 = %1
        jmp @loop
    """

    _check_pre_post(pre1, post)
    _check_pre_post(pre2, post)
