import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

fail_list = [
    """
@public
def foo() -> int128[2]:
    return [3,chain.id]
    """,
    """
@public
def foo() -> decimal(wei / sec):
    x: int128(wei) = as_wei_value(5, "finney")
    y: int128 = chain.id + 50
    return x / y
    """,
    """
@public
def foo():
    x: bytes[10] = slice("cow", start=0, len=chain.id)
    """,
    """
@public
def foo():
    x: int128 = 7
    y: int128 = min(x, chain.id)
    """,
    """
a: map(timestamp, int128)

@public
def add_record():
    self.a[chain.id] = chain.id + 20
    """,
    """
a: map(int128, timestamp)

@public
def add_record():
    self.a[chain.id] = chain.id + 20
    """,
    """
@public
def foo(inp: bytes[10]) -> bytes[3]:
    return slice(inp, start=chain.id, len=3)
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_chain_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
@constant
def get_chain_id() -> uint256:
    return chain.id
    """,
    """
@public
@constant
def check_chain_id(c: uint256) -> bool:
    return chain.id == c
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_chain_success(good_code):
    assert compiler.compile_code(good_code) is not None


def test_chainid_operation(get_contract_with_gas_estimation):
    code = """
@public
@constant
def get_chain_id() -> uint256:
    return chain.id
    """
    c = get_contract_with_gas_estimation(code)
    assert c.get_chain_id() == 0  # Default value of py-evm
