import pytest
from eth_tester.exceptions import TransactionFailed

from vyper import compiler
from vyper.exceptions import StructureException, TypeMismatch


def test_variable_assignment(get_contract, keccak):
    code = """
@external
def foo() -> Bytes[4]:
    bar: Bytes[4] = slice(msg.data, 0, 4)
    return bar
"""

    contract = get_contract(code)

    assert contract.foo() == bytes(keccak(text="foo()")[:4])


def test_slicing_start_index_other_than_zero(get_contract):
    code = """
@external
def foo(_value: uint256) -> uint256:
    bar: Bytes[32] = slice(msg.data, 4, 32)
    return convert(bar, uint256)
"""

    contract = get_contract(code)

    assert contract.foo(42) == 42


def test_get_full_calldata(get_contract, keccak, w3):
    code = """
@external
def foo(bar: uint256) -> Bytes[36]:
    data: Bytes[36] = slice(msg.data, 0, 36)
    return data
"""
    contract = get_contract(code)

    # 2fbebd38000000000000000000000000000000000000000000000000000000000000002a
    method_id = keccak(text="foo(uint256)").hex()[2:10]  # 2fbebd38
    encoded_42 = w3.to_bytes(42).hex()  # 2a
    expected_result = method_id + "00" * 31 + encoded_42

    assert contract.foo(42).hex() == expected_result


@pytest.mark.parametrize("bar", [0, 1, 42, 2**256 - 1])
def test_calldata_private(get_contract, bar):
    code = """
@external
def foo(bar: uint256) -> uint256:
    data: Bytes[32] = slice(msg.data, 4, 32)
    return convert(data, uint256)
    """
    c = get_contract(code)

    assert c.foo(bar) == bar


def test_memory_pointer_advances_appropriately(get_contract, keccak):
    code = """
@external
def foo() -> (uint256, Bytes[4], uint256):
    a: uint256 = max_value(uint256)
    b: Bytes[4] = slice(msg.data, 0, 4)
    c: uint256 = max_value(uint256)

    return (a, b, c)
"""
    contract = get_contract(code)

    assert contract.foo() == [2**256 - 1, bytes(keccak(text="foo()")[:4]), 2**256 - 1]


def test_assignment_to_storage(w3, get_contract, keccak):
    code = """
cache: public(Bytes[4])

@external
def foo():
    self.cache = slice(msg.data, 0, 4)
"""
    acct = w3.eth.accounts[0]
    contract = get_contract(code)

    contract.foo(transact={"from": acct})
    assert contract.cache() == bytes(keccak(text="foo()")[:4])


def test_get_len(get_contract):
    code = """
@external
def foo(bar: uint256) -> uint256:
    return len(msg.data)
"""
    contract = get_contract(code)

    assert contract.foo(42) == 36


fail_list = [
    (
        """
@external
def foo() -> Bytes[4]:
    bar: Bytes[4] = msg.data
    return bar
    """,
        StructureException,
    ),
    (
        """
@external
def foo() -> Bytes[7]:
    bar: Bytes[7] = concat(msg.data, 0xc0ffee)
    return bar
    """,
        StructureException,
    ),
    (
        """
@external
def foo() -> uint256:
    bar: uint256 = convert(msg.data, uint256)
    return bar
    """,
        StructureException,
    ),
    (
        """
a: HashMap[Bytes[10], uint256]

@external
def foo():
    self.a[msg.data] += 1
    """,
        StructureException,
    ),
    (
        """
@external
def foo(bar: uint256) -> bytes32:
    ret_val: bytes32 = slice(msg.data, 4, 32)
    return ret_val
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_usages_compile_error(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


def test_runtime_failure_bounds_check(get_contract):
    code = """
@external
def foo(_value: uint256) -> uint256:
    val: Bytes[40] = slice(msg.data, 0, 40)
    return convert(slice(val, 4, 32), uint256)
"""

    contract = get_contract(code)

    with pytest.raises(TransactionFailed):
        contract.foo(42)
