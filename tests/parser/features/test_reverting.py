import pytest
from eth_tester.exceptions import TransactionFailed

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_revert_reason(w3, assert_tx_failed, tester, keccak, get_contract_with_gas_estimation):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    data: Bytes[100] = _abi_encode(val, method_id=method_id("NoFives(uint256)"))
    raw_revert(data)
    """

    assert_tx_failed(
        lambda: get_contract_with_gas_estimation(reverty_code).foo(transact={}),
        TransactionFailed,
        exc_text=(
            "execution reverted: "
            "b'.\\x7f\\xb9\\x1f"
            "\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"
            "\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00"
            "\\x00\\x00\\x00\\x05'"
        ),
    )
