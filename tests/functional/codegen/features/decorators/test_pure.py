import pytest

from vyper.compiler import compile_code
from vyper.exceptions import FunctionDeclarationException, StateAccessViolation


def test_pure_operation(get_contract):
    code = """
@pure
@external
def foo() -> int128:
    return 5
    """
    c = get_contract(code)
    assert c.foo() == 5


def test_pure_call(get_contract):
    code = """
@pure
@internal
def _foo() -> int128:
    return 5

@pure
@external
def foo() -> int128:
    return self._foo()
    """
    c = get_contract(code)
    assert c.foo() == 5


def test_pure_interface(get_contract):
    code1 = """
@pure
@external
def foo() -> int128:
    return 5
    """
    code2 = """
interface Foo:
    def foo() -> int128: pure

@pure
@external
def foo(a: address) -> int128:
    return staticcall Foo(a).foo()
    """
    c1 = get_contract(code1)
    c2 = get_contract(code2)
    assert c2.foo(c1.address) == 5


def test_invalid_envar_access(get_contract):
    code = """
@pure
@external
def foo() -> uint256:
    return chain.id
    """
    with pytest.raises(StateAccessViolation):
        compile_code(code)


def test_invalid_state_access(get_contract, assert_compile_failed):
    code = """
x: uint256

@pure
@external
def foo() -> uint256:
    return self.x
    """
    with pytest.raises(StateAccessViolation):
        compile_code(code)


def test_invalid_self_access():
    code = """
@pure
@external
def foo() -> address:
    return self
    """
    with pytest.raises(StateAccessViolation):
        compile_code(code)


def test_invalid_call():
    code = """
@view
@internal
def _foo() -> uint256:
    return 5

@pure
@external
def foo() -> uint256:
    return self._foo()  # Fails because of calling non-pure fn
    """
    with pytest.raises(StateAccessViolation):
        compile_code(code)


def test_invalid_conflicting_decorators():
    code = """
@pure
@external
@payable
def foo() -> uint256:
    return 5
    """
    with pytest.raises(FunctionDeclarationException):
        compile_code(code)
