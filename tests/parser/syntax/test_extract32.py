import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatch

fail_list = [
    """
@external
def foo() -> uint256:
    return extract32(b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0)
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_extract32_fail(bad_code):

    with raises(TypeMismatch):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo() -> uint256:
    return extract32(
        b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc",
        0,
        output_type=uint256
    )
    """,
    """
x: Bytes[100]
@external
def foo() -> uint256:
    self.x = b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 0, output_type=uint256)
    """,
    """
x: Bytes[100]
@external
def foo() -> uint256:
    self.x = b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 1, output_type=uint256)
""",
]


@pytest.mark.parametrize("good_code", valid_list)
def test_extract32_success(good_code):
    assert compiler.compile_code(good_code) is not None
