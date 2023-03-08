import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, StructureException

invalid_list = [
    (
        """
b: HashMap[uint256, uint256]
@external
def foo():
    x: int128 = self.b[-5]
    """,
        InvalidType,
    ),
    (
        """
b: HashMap[int128, int128]
@external
def foo():
    x: int128 = self.b[5.7]
    """,
        InvalidType,
    ),
    (
        """
b: HashMap[int128, int128]
@external
def foo():
    self.b[3] = 5.6
    """,
        InvalidType,
    ),
    (
        """
event Foo:
    a: uint256

b: HashMap[uint256, Foo]
    """,
        StructureException,
    ),
    (
        """
a: HashMap[address, uint8]
b: HashMap[address, uint8]
c: HashMap[address, (HashMap[address, uint8], HashMap[address, uint8])]
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", invalid_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
b: HashMap[int128, int128]
@external
def foo():
    x: int128 = self.b[5]
    """,
    """
b: HashMap[decimal, int128]
@external
def foo():
    x: int128 = self.b[5.0]
    """,
    """
b: HashMap[int128, int128]
@external
def foo():
    self.b[3] = -5
    """,
    """
b: HashMap[int128, int128]
@external
def foo():
    self.b[-3] = 5
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
