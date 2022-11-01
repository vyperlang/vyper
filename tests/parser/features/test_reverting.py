import re

import pytest
from eth_abi import encode
from eth_tester.exceptions import TransactionFailed

from vyper.utils import keccak256

pytestmark = pytest.mark.usefixtures("memory_mocker")


def build_revert_bytestring(errorDecl, *data):
    # revert bytes should be 4-byte selector (from keccak of error definition)
    # followed by abi-encoded data
    error_selector = keccak256(bytes(errorDecl, "utf-8"))[:4]
    match = re.search(r"\((.*?)\)", errorDecl)  # .group(1)
    if match and match.group(1) != "":
        arg_types = match.group(1)
        encoded_data = encode(arg_types.split(","), data)
        return b"".join([error_selector, encoded_data])
    else:
        return error_selector


def test_revert_reason(w3, assert_tx_failed, tester, keccak, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    data: Bytes[4] = method_id("NoFives()")
    raw_revert(data)
    """

    revert_bytes = build_revert_bytestring("NoFives()")

    assert_tx_failed(
        lambda: get_contract_with_gas_estimation(reverty_code).foo(transact={}),
        TransactionFailed,
        exc_text=f"execution reverted: {revert_bytes}",
    )


def test_revert_reason_typed(
    w3, assert_tx_failed, tester, keccak, get_contract_with_gas_estimation
):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    data: Bytes[100] = _abi_encode(val, method_id=method_id("NoFives(uint256)"))
    raw_revert(data)
    """

    revert_bytes = build_revert_bytestring("NoFives(uint256)", 5)

    assert_tx_failed(
        lambda: get_contract_with_gas_estimation(reverty_code).foo(transact={}),
        TransactionFailed,
        exc_text=f"execution reverted: {revert_bytes}",
    )
