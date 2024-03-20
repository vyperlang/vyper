import pytest
from eth.codecs import abi
from eth_tester.exceptions import TransactionFailed

from vyper.utils import method_id

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_revert_reason(w3, tx_failed, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    data: Bytes[4] = method_id("NoFives()")
    raw_revert(data)
    """

    revert_bytes = method_id("NoFives()")

    with tx_failed(TransactionFailed, exc_text=f"execution reverted: {revert_bytes}"):
        get_contract_with_gas_estimation(reverty_code).foo(transact={})


def test_revert_reason_typed(w3, tx_failed, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    data: Bytes[100] = _abi_encode(val, method_id=method_id("NoFives(uint256)"))
    raw_revert(data)
    """

    revert_bytes = method_id("NoFives(uint256)") + abi.encode("(uint256)", (5,))

    with tx_failed(TransactionFailed, exc_text=f"execution reverted: {revert_bytes}"):
        get_contract_with_gas_estimation(reverty_code).foo(transact={})


def test_revert_reason_typed_no_variable(w3, tx_failed, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    raw_revert(_abi_encode(val, method_id=method_id("NoFives(uint256)")))
    """

    revert_bytes = method_id("NoFives(uint256)") + abi.encode("(uint256)", (5,))

    with tx_failed(TransactionFailed, exc_text=f"execution reverted: {revert_bytes}"):
        get_contract_with_gas_estimation(reverty_code).foo(transact={})
