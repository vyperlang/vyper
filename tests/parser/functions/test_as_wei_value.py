import pytest

from vyper.exceptions import InvalidLiteral, OverflowException


def test_ext_call(w3, side_effects_contract, assert_side_effects_invoked, get_contract):
    code = """
@external
def foo(a: Foo) -> uint256:
    return as_wei_value(a.foo(7), "ether")

interface Foo:
    def foo(x: uint8) -> uint8: nonpayable
    """

    c1 = side_effects_contract("uint8")
    c2 = get_contract(code)

    assert c2.foo(c1.address) == w3.to_wei(7, "ether")
    assert_side_effects_invoked(c1, lambda: c2.foo(c1.address, transact={}))


def test_internal_call(w3, get_contract_with_gas_estimation):
    code = """
@external
def foo() -> uint256:
    return as_wei_value(self.bar(), "ether")

@internal
def bar() -> uint8:
    return 7
    """

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == w3.to_wei(7, "ether")


fail_list = [
    (
        """
# Test for negative argument
@external
def foo():
    x: uint256 = as_wei_value(-3, "szabo")
    """,
        InvalidLiteral,
    ),
    (
        """
# Test for 256 bits overflows
@external
def foo():
    x: uint256 = as_wei_value(max_value(uint248), "ether")
    """,
        OverflowException,
    ),
]


@pytest.mark.parametrize("bad_code,exception", fail_list)
def test_abi_decode_length_mismatch(get_contract, assert_compile_failed, bad_code, exception):
    assert_compile_failed(lambda: get_contract(bad_code), exception)


valid_list = [
    """
@external
def foo():
    a:int24 = 31
    b:uint136 = 31
    x: uint256 = as_wei_value(a, "szabo") + as_wei_value(b, "ether")
    """
]


@pytest.mark.parametrize("good_code", valid_list)
def test_as_wei_success(good_code, get_contract_with_gas_estimation):
    assert get_contract_with_gas_estimation(good_code) is not None


def test_as_wei_revert(get_contract, assert_tx_failed):
    code = """
@external
def foo() -> uint256:
    a: uint248 = max_value(uint248)
    return as_wei_value(a, "grand")
    """
    contract = get_contract(code)
    assert_tx_failed(lambda: contract.foo())
