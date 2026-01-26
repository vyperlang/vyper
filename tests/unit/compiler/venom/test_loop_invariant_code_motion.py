import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import LoopInvariantCodeMotionPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([LoopInvariantCodeMotionPass])


def test_simple_loop_invariant():
    pre = """
    main:
        %x = source
        jmp @loop_header
    loop_header:
        %cond = lt %x, 10
        jnz %cond, @loop_body, @exit
    loop_body:
        %mul = mul %x, 2
        %use = %mul
        jmp @loop_header
    exit:
        sink %use
    """

    post = """
    main:
        %x = source
        %cond = lt %x, 10
        %mul = mul %x, 2
        %use = %mul
        jmp @loop_header
    loop_header:
        jnz %cond, @loop_body, @exit
    loop_body:
        jmp @loop_header
    exit:
        sink %use
    """

    _check_pre_post(pre, post)


def test_loop_variant_not_hoisted():
    pre = """
    main:
        %start = source
        jmp @loop_header
    loop_header:
        %iter = phi @main, %start, @loop_body, %next
        %cond = lt %iter, 10
        jnz %cond, @loop_body, @exit
    loop_body:
        %next = add %iter, 1
        %variant = add %iter, 2
        %use = %variant
        jmp @loop_header
    exit:
        sink %use
    """

    _check_pre_post(pre, pre)


def test_branch_local_invariant_not_hoisted():
    pre = """
    main:
        %x = source
        %flag = source
        jmp @loop_header
    loop_header:
        %cond = lt %x, 10
        jnz %cond, @loop_body, @exit
    loop_body:
        jnz %flag, @loop_then, @loop_continue
    loop_then:
        %inv = add %x, 1
        %use = %inv
        jmp @loop_continue
    loop_continue:
        jmp @loop_header
    exit:
        sink %use
    """

    post = """
    main:
        %x = source
        %flag = source
        %cond = lt %x, 10
        jmp @loop_header
    loop_header:
        jnz %cond, @loop_body, @exit
    loop_body:
        jnz %flag, @loop_then, @loop_continue
    loop_then:
        %inv = add %x, 1
        %use = %inv
        jmp @loop_continue
    loop_continue:
        jmp @loop_header
    exit:
        sink %use
    """

    _check_pre_post(pre, post)


def test_storage_read_hoisted_without_writes():
    pre = """
    main:
        %k = source
        jmp @loop_header
    loop_header:
        %cond = lt %k, 10
        jnz %cond, @loop_body, @exit
    loop_body:
        %v = sload 0
        %use = %v
        jmp @loop_header
    exit:
        sink %use
    """

    post = """
    main:
        %k = source
        %cond = lt %k, 10
        %v = sload 0
        %use = %v
        jmp @loop_header
    loop_header:
        jnz %cond, @loop_body, @exit
    loop_body:
        jmp @loop_header
    exit:
        sink %use
    """

    _check_pre_post(pre, post)


def test_storage_read_not_hoisted_with_writes():
    pre = """
    main:
        %k = source
        jmp @loop_header
    loop_header:
        %cond = lt %k, 10
        jnz %cond, @loop_body, @exit
    loop_body:
        sstore 0, 1
        %v = sload 0
        %use = %v
        jmp @loop_header
    exit:
        sink %use
    """

    post = """
    main:
        %k = source
        %cond = lt %k, 10
        jmp @loop_header
    loop_header:
        jnz %cond, @loop_body, @exit
    loop_body:
        sstore 0, 1
        %v = sload 0
        %use = %v
        jmp @loop_header
    exit:
        sink %use
    """

    _check_pre_post(pre, post)
