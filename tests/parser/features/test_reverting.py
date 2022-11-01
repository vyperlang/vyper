import pytest
from eth_tester.exceptions import TransactionFailed

from vyper.utils import keccak256

pytestmark = pytest.mark.usefixtures("memory_mocker")


def method_id(method_str: str) -> bytes:
    return keccak256(bytes(method_str, "utf-8"))[:4]


def test_revert_reason(w3, assert_tx_failed, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    data: Bytes[4] = method_id("NoFives()")
    raw_revert(data)
    """

    revert_bytes = method_id("NoFives()")

    assert_tx_failed(
        lambda: get_contract_with_gas_estimation(reverty_code).foo(transact={}),
        TransactionFailed,
        exc_text=f"execution reverted: {revert_bytes}",
    )


def test_revert_reason_typed(w3, assert_tx_failed, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    data: Bytes[100] = _abi_encode(val, method_id=method_id("NoFives(uint256)"))
    raw_revert(data)
    """

    revert_bytes = method_id("NoFives(uint256)") + (5).to_bytes(32, "big")

    assert_tx_failed(
        lambda: get_contract_with_gas_estimation(reverty_code).foo(transact={}),
        TransactionFailed,
        exc_text=f"execution reverted: {revert_bytes}",
    )
