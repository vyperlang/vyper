import pytest

from vyper import compiler
from vyper.exceptions import TypeMismatch, UnfoldableNode

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
    """,
    """
@external
def foo(x: Bytes[32]) -> uint256:
    return _abi_decode(x, uint256, unwrap_tuple=(0 < 1))
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_abi_decode_success(good_code):
    assert compiler.compile_code(good_code) is not None


@pytest.mark.xfail(raises=UnfoldableNode)
def test_abi_decode_unwrap_tuple_foldable_expr():
    code = """
@external
def f(x: Bytes[32]) -> uint256:
    return abi_decode(x, uint256, unwrap_tuple=empty(bool))
    """
    assert compiler.compile_code(code) is not None
