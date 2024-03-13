import pytest

from vyper.exceptions import StructureException


def test_continue1(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> bool:
    for i: uint256 in range(2):
        continue
        return False
    return True
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo()


def test_continue2(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> int128:
    x: int128 = 0
    for i: int128 in range(3):
        x += 1
        continue
        x -= 1
    return x
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 3


def test_continue3(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> int128:
    x: int128 = 0
    for i: int128 in range(3):
        x += i
        continue
    return x
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 3


def test_continue4(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> int128:
    x: int128 = 0
    for i: int128 in range(6):
        if i % 2 == 0:
            continue
        x += 1
    return x
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 3


fail_list = [
    (
        """
@external
def foo():
    a: uint256 = 3
    continue
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    if True:
        continue
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    for i: uint256 in [1, 2, 3]:
        b: uint256 = i
    if True:
        continue
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
