import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, TypeMismatch

fail_list = [
    (
        """
@external
def foo(x: Bytes[1]) -> Bytes[64]:
    return _abi_encode(x)
    """,
        TypeMismatch,  # output type too small
    ),
    (
        """
@external
def foo(x: Bytes[1]) -> Bytes[32]:
    return _abi_encode(x, ensure_tuple=False)
    """,
        TypeMismatch,  # output type too small
    ),
    (
        """
@external
def foo(x: uint256) -> Bytes[36]:
    _ensure_tuple: bool = False
    _method_id: Bytes[4] = method_id("foo()")
    return _abi_encode(x, ensure_tuple=_ensure_tuple, method_id=_method_id)
    """,
        TypeMismatch,  # ensure_tuple and method_id both must be literals
    ),
    (
        """
@external
def foo(x: uint256) -> Bytes[36]:
    return _abi_encode(x, method_id=b"abcde")
    """,
        TypeMismatch,  # len(method_id) must be less than 4
    ),
    (
        """
@external
def foo(x: uint256) -> Bytes[36]:
    return _abi_encode(x, method_id=0x1234567890)
    """,
        TypeMismatch,  # len(method_id) must be less than 4
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_slice_fail(bad_code, exc):

    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo(x: uint256) -> Bytes[32]:
    return _abi_encode(x)
    """,
    """
@external
def foo(x: Bytes[1]) -> Bytes[65]:
    return _abi_encode(x)
    """,
    """
@external
def foo(x: Bytes[1]) -> Bytes[33]:
    return _abi_encode(x, ensure_tuple=False)
    """,
    """
@external
def foo(x: Bytes[1]) -> Bytes[40]:
    return _abi_encode(x, method_id=method_id("exec()"))
    """,
    """
@external
def foo(x: Bytes[1]) -> Bytes[40]:
    return _abi_encode(x, method_id=0x123455678)
    """,
    """
@external
def foo(x: Bytes[1]) -> Bytes[33]:
    return _abi_encode(x)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_slice_success(good_code):
    assert compiler.compile_code(good_code) is not None
