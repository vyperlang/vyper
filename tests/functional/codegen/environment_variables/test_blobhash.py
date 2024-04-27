import pytest
from eth.vm.forks.cancun.constants import BLOB_BASE_FEE_UPDATE_FRACTION, MIN_BLOB_BASE_FEE
from eth.vm.forks.cancun.state import fake_exponential
from hexbytes import HexBytes
from eth.codecs import abi



@pytest.mark.requires_evm_version("cancun")
def test_blobbasefee(get_contract_with_gas_estimation, w3, keccak, tx_failed):
    code = """
x: public(bytes32)
    
@external
def set_blobhash(i: uint256):
    self.x = blobhash(i)
"""
    c = get_contract_with_gas_estimation(code)

    a0 = w3.eth.account.from_key(f"0x{'00' * 31}01")

    # to get the expected versioned hashes:
    #
    # from eth_account._utils.typed_transactions import BlobTransaction
    # blob_transaction = BlobTransaction.from_bytes(HexBytes(signed.rawTransaction))
    # print(blob_transaction.blob_data.versioned_hashes)
    expected_versioned_hash = "0x015a5c97e3cc516f22a95faf7eefff00eb2fee7a65037fde07ac5446fc93f2a0"

    def _send_tx_with_blobs(num_blobs, input_idx):
        text = b"Vyper is the language of the sneks"
        # Blobs contain 4096 32-byte field elements.
        blob_data = text.rjust(32 * 4096)

        sig = keccak("set_blobhash(uint256)".encode()).hex()[:8]
        encoded = abi.encode("uint256", input_idx).hex()
        tx = {
            "type": 3,
            "chainId": 1337,
            "from": a0.address,
            "to": c.address,
            "value": 0,
            "gas": 210000,
            "maxFeePerGas": 10**10,
            "maxPriorityFeePerGas": 10**10,
            "maxFeePerBlobGas": 10**10,
            "nonce": w3.eth.get_transaction_count(a0.address),
            "data": f"0x{sig}{encoded}"
        }

        signed = a0.sign_transaction(tx, blobs=[blob_data] * num_blobs)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        transaction = w3.eth.get_transaction(tx_hash)

        # sanity check
        assert len(transaction["blobVersionedHashes"]) == num_blobs
        for i in range(num_blobs):
            assert transaction["blobVersionedHashes"][i] == HexBytes(expected_versioned_hash)

    _send_tx_with_blobs(1, 0)
    assert "0x" + c.x().hex() == expected_versioned_hash

    _send_tx_with_blobs(6, 5)
    assert "0x" + c.x().hex() == expected_versioned_hash

    _send_tx_with_blobs(1, 1)
    assert c.x() == b"\x00" * 32



