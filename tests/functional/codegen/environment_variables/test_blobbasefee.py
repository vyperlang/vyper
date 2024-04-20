import pytest
from eth.codecs import abi
from eth.vm.forks.cancun.constants import BLOB_BASE_FEE_UPDATE_FRACTION, MIN_BLOB_BASE_FEE
from eth.vm.forks.cancun.state import fake_exponential


@pytest.mark.requires_evm_version("cancun")
def test_blobbasefee(get_contract_with_gas_estimation, w3):
    code = """
@external
@view
def get_blobbasefee() -> uint256:
    return block.blobbasefee
"""
    c = get_contract_with_gas_estimation(code)

    assert c.get_blobbasefee() == MIN_BLOB_BASE_FEE

    a0 = w3.eth.account.from_key(f"0x{'00' * 31}01")

    text = "Vyper is the language of the sneks"
    encoded_text = abi.encode("(string)", (text,))
    # Blobs contain 4096 32-byte field elements. Subtract the length of the encoded text
    # divided into 32-byte chunks from 4096 and pad the rest with zeros.
    blob_data = (b"\x00" * 32 * (4096 - len(encoded_text) // 32)) + encoded_text

    for _i in range(10):
        tx = {
            "type": 3,
            "chainId": 1337,
            "from": a0.address,
            "to": "0xb45BEc6eeCA2a09f4689Dd308F550Ad7855051B5",
            "value": 0,
            "gas": 21000,
            "maxFeePerGas": 10**10,
            "maxPriorityFeePerGas": 10**10,
            "maxFeePerBlobGas": 10**10,
            "nonce": w3.eth.get_transaction_count(a0.address),
        }

        signed = a0.sign_transaction(tx, blobs=[blob_data] * 6)
        w3.eth.send_raw_transaction(signed.rawTransaction)

        block = w3.eth.get_block("latest")
        excess_blob_gas = block["excessBlobGas"]
        expected_blobbasefee = fake_exponential(
            MIN_BLOB_BASE_FEE, excess_blob_gas, BLOB_BASE_FEE_UPDATE_FRACTION
        )

        assert c.get_blobbasefee() == expected_blobbasefee

    # sanity check that blobbasefee has increased above the minimum
    assert c.get_blobbasefee() > MIN_BLOB_BASE_FEE
