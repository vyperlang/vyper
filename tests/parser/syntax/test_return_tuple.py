import pytest

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException

fail_list = [
    """
@external
def unmatched_tupl_length() -> (Bytes[8], int128, Bytes[8]):
    return "test", 123
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_tuple_return_fail(bad_code):

    with pytest.raises(FunctionDeclarationException):
        compiler.compile_code(bad_code)


def test_self_call_in_return_tuple(get_contract):
    code = """
@internal
def _foo() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,14,15]
    return 3

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return 1, 2, self._foo(), 4, 5
    """

    c = get_contract(code)

    assert c.foo() == [1, 2, 3, 4, 5]


def test_call_in_call(get_contract):
    code = """
@internal
def _foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256, uint256, uint256, uint256):
    return 1, a, b, c, 5

@internal
def _foo2() -> uint256:
    a: uint256[10] = [6,7,8,9,10,11,12,13,15,16]
    return 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return self._foo(2, 3, self._foo2())
    """

    c = get_contract(code)

    assert c.foo() == [1, 2, 3, 4, 5]


def test_nested_calls_in_tuple_return(get_contract):
    code = """
@internal
def _foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return 415, 3

@internal
def _foo2(a: uint256) -> uint256:
    b: uint256[10] = [6,7,8,9,10,11,12,13,14,15]
    return 99

@internal
def _foo3(a: uint256, b: uint256) -> uint256:
    c: uint256[10] = [14,15,16,17,18,19,20,21,22,23]
    return 42

@internal
def _foo4() -> uint256:
    c: uint256[10] = [14,15,16,17,18,19,20,21,22,23]
    return 4

@external
def foo() -> (uint256, uint256, uint256, uint256, uint256):
    return 1, 2, self._foo(6, 7, self._foo2(self._foo3(9, 11)))[1], self._foo4(), 5
    """

    c = get_contract(code)

    assert c.foo() == [1, 2, 3, 4, 5]


def test_external_call_in_return_tuple(get_contract):
    code = """
@view
@external
def foo() -> (uint256, uint256):
    return 3, 4
    """

    code2 = """
interface Foo:
    def foo() -> (uint256, uint256): view

@external
def foo(a: address) -> (uint256, uint256, uint256, uint256, uint256):
    return 1, 2, Foo(a).foo()[0], 4, 5
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == [1, 2, 3, 4, 5]


def test_nested_external_call_in_return_tuple(get_contract):
    code = """
@view
@external
def foo() -> (uint256, uint256):
    return 3, 4

@view
@external
def bar(a: uint256) -> uint256:
    return a+1
    """

    code2 = """
interface Foo:
    def foo() -> (uint256, uint256): view
    def bar(a: uint256) -> uint256: view

@external
def foo(a: address) -> (uint256, uint256, uint256, uint256, uint256):
    return 1, 2, Foo(a).foo()[0], 4, Foo(a).bar(Foo(a).foo()[1])
    """

    c = get_contract(code)
    c2 = get_contract(code2)

    assert c2.foo(c.address) == [1, 2, 3, 4, 5]
