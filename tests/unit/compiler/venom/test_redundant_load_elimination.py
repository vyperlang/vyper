import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import RedundantLoadElimination

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([RedundantLoadElimination])


def test_basic_redundant_load():
    pre = """
        _global:
            %val = 42
            mstore 0, %val
            %loaded1 = mload 0
            %loaded2 = mload 0
            stop
    """
    post = """
        _global:
            %val = 42
            mstore 0, %val
            %loaded1 = mload 0
            %loaded2 = store %loaded1
            stop
    """
    _check_pre_post(pre, post)


def test_redundant_load_after_store():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1
            %loaded1 = mload 0
            mstore 0, %val2
            %loaded2 = mload 0
            stop
    """
    _check_pre_post(pre, pre)


def test_redundant_load_different_locations():
    pre = """
        _global:
            %val1 = 42
            %val2 = 24
            mstore 0, %val1
            %loaded1 = mload 0
            mstore 32, %val2
            %loaded2 = mload 32
            stop
    """
    _check_pre_post(pre, pre)


def test_redundant_load_in_branches():
    pre = """
        _global:
            %cond = 1
            %val = 42
            mstore 0, %val
            jnz %cond, @then, @else
        then:
            %loaded1 = mload 0
            jmp @merge
        else:
            %loaded2 = mload 0
            jmp @merge
        merge:
            %loaded3 = mload 0
            stop
    """
    _check_pre_post(pre, pre)


def test_not_redundant_load_with_phi():
    pre = """
        _global:
            %cond = 1
            %val1 = 42
            %val2 = 24
            jnz %cond, @then, @else
        then:
            mstore 0, %val1
            %loaded1 = mload 0
            jmp @merge
        else:
            mstore 0, %val2
            %loaded2 = mload 0
            jmp @merge
        merge:
            %loaded3 = mload 0
            stop
    """
    _check_pre_post(pre, pre)


def test_redundant_load_in_loop():
    pre = """
        _global:
            %val = 42
            %i = 0
            mstore 0, %val
            %loaded1 = mload 0
            jmp @loop
        loop:
            %cond = lt %i, 5
            jnz %cond, @body, @exit
        body:
            %loaded2 = mload 0
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    post = """
        _global:
            %val = 42
            %i = 0
            mstore 0, %val
            %loaded1 = mload 0
            jmp @loop
        loop:
            %cond = lt %i, 5
            jnz %cond, @body, @exit
        body:
            %loaded2 = store %loaded1
            %i = add %i, 1
            jmp @loop
        exit:
            stop
    """
    _check_pre_post(pre, post)

if __name__ == "__main__":
    test_redundant_load_in_loop()
