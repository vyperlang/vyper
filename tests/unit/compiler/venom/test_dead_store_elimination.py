import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import DeadStoreElimination

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([DeadStoreElimination])


def test_basic_dead_store():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1  ; Dead store - overwritten before read
            mstore 0, 10     ; Dead store - overwritten before read
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            nop
            nop
            mstore 0, %val2
            %loaded = mload 0
            stop
    """
    _check_pre_post(pre, post)


def test_never_read_store():
    pre = """
        _global:
            %val = 42
            mstore 0, %val  ; Dead store - never read
            stop
    """
    post = """
        _global:
            %val = 42
            nop
            stop
    """
    _check_pre_post(pre, post)


def test_live_store():
    pre = """
        _global:
            %val = 42
            mstore 0, %val
            %loaded = mload 0  ; Makes the store live
            stop
    """
    _check_pre_post(pre, pre)  # Should not change


def test_dead_store_different_locations():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1   ; Dead store - never read
            mstore 32, %val2  ; Live store
            %loaded = mload 32
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            nop
            mstore 32, %val2
            %loaded = mload 32
            stop
    """
    _check_pre_post(pre, post)


def test_dead_store_in_branches():
    pre = """
        _global:
            %cond = 1
            %val1 = 42
            %val2 = 24
            jnz %cond, @then, @else
        then:
            mstore 0, %val1  ; Dead store - overwritten in merge
            jmp @merge
        else:
            mstore 0, %val2  ; Dead store - overwritten in merge
            jmp @merge
        merge:
            %val3 = 84
            mstore 0, %val3
            %loaded = mload 0  ; Only reads val3
            stop
    """
    post = """
        _global:
            %cond = 1
            %val1 = 42
            %val2 = 24
            jnz %cond, @then, @else
        then:
            nop
            jmp @merge
        else:
            nop
            jmp @merge
        merge:
            %val3 = 84
            mstore 0, %val3
            %loaded = mload 0
            stop
    """
    _check_pre_post(pre, post)


def test_dead_store_in_loop():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            %i = 0
            mstore 0, %val1  ; Dead store - overwritten in loop before any read
            jmp @loop
        loop:
            %cond = lt %i, 5
            jnz %cond, @body, @exit
        body:
            mstore 0, %val2
            %loaded = mload 0  ; Only reads val2
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            %i = 0
            nop
            jmp @loop
        loop:
            %cond = lt %i, 5
            jnz %cond, @body, @exit
        body:
            mstore 0, %val2
            %loaded = mload 0
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    _check_pre_post(pre, post)


def test_multiple_dead_stores():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84
            mstore 0, %val1  ; Dead store - overwritten before read
            mstore 0, %val2  ; Dead store - overwritten before read
            mstore 0, %val3
            %loaded = mload 0  ; Only reads val3
            stop
    """
    post = """
        _global:
            %val1 = 42
            %val2 = 24
            %val3 = 84
            nop
            nop
            mstore 0, %val3
            %loaded = mload 0
            stop
    """
    _check_pre_post(pre, post)
