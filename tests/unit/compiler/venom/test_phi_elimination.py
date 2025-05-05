from tests.venom_utils import PrePostChecker
from vyper.venom.passes import PhiEliminationPass

_check_pre_post = PrePostChecker([PhiEliminationPass])


def test_phi_elim_loop():
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
        %2 = %1
        jmp @condition
    condition:
        %3 = phi @main, %1, @body, %6
        jnz %cond, @exit, @body
    body:
        %4 = %2
        %another_cond = calldataload 200
    then:
        %6:1 = %4
        jmp @join
    else:
        %6:2 = %1
        jmp @join
    join:
        %6 = phi @then, %6:1, @else, %6:2
        %cond = calldataload 100
        jnz %another_cond, @condition, @exit
    exit:
        %5 = phi @condition, %3, @body, %4
        sink %5
    """

    post = """
    main:
        %1 = param
        %2 = %1
        jmp @condition
    condition:
        %3 = %1
        jnz %cond, @exit, @body
    body:
        %4 = %2
        %another_cond = calldataload 200
    then:
        %6:1 = %4
        jmp @join
    else:
        %6:2 = %1
        jmp @join
    join:
        %6 = %1
        %cond = calldataload 100
        jnz %another_cond, @condition, @exit
    exit:
        %5 = %1
        sink %5
    """

    _check_pre_post(pre, post)
