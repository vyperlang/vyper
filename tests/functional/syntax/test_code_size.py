import pytest

from vyper import compiler
from vyper.exceptions import StructureException

fail_list = [
    """
@external
def foo() -> int128:
    x: int128 = 45
    return x.codesize
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):
    with pytest.raises(StructureException):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo() -> uint256:
    x: address = 0x1234567890123456789012345678901234567890
    return x.codesize
    """,
    """
@external
def foo() -> uint256:
    return self.codesize
    """,
    """
struct Foo:
    t: address
foo: Foo

@external
def bar() -> uint256:
    return self.foo.t.codesize
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
