import pytest

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    (
        """
@external
def foo(j: uint256) -> bool:
    s: bool = _abi_decode(j, bool, unwrap_tuple= False)
    return s
    """,
        TypeMismatch,
    ),
    (
        """
@external
def bar(j: String[32]) -> bool:
    s: bool = _abi_decode(j, bool, unwrap_tuple= False)
    return s
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_abi_decode_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo(x: Bytes[32]) -> uint256:
    return _abi_decode(x, uint256)
    """
]


@pytest.mark.parametrize("good_code", valid_list)
def test_abi_decode_success(good_code):
    assert compiler.compile_code(good_code) is not None
