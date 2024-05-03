import pytest
from eth.codecs import abi
from hexbytes import HexBytes

from vyper import compiler

valid_list = [
    """
@external
@view
def foo() -> bytes32:
    return blobhash(0)
    """,
    """
@external
@view
def foo() -> bytes32:
    a: bytes32 = 0x0000000000000000000000000000000000000000000000000000000000000005
    a = blobhash(2)
    return a
    """,
    """
@external
@view
def foo() -> bytes32:
    a: bytes32 = blobhash(0)
    assert a != empty(bytes32)
    return a
    """,
    """
@external
@view
def foo() -> bytes32:
    a: bytes32 = blobhash(1337)
    assert a == empty(bytes32)
    return a
    """,
]


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("good_code", valid_list)
def test_blobhash_success(good_code):
    assert compiler.compile_code(good_code) is not None
    assembly = compiler.compile_code(good_code, output_formats=["asm"])["asm"].split(" ")
    assert "BLOBHASH" in assembly


@pytest.mark.requires_evm_version("cancun")
def test_get_blobhashes(get_contract_with_gas_estimation, w3, keccak, tx_failed):
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
    expected_versioned_hash = "0x0168dea5bd14ec82691edc861dcee360342a921c1664b02745465f6c42239f06"

    def _send_tx_with_blobs(num_blobs, input_idx):
        text = b"Long live the BLOBs!"
        # BLOBs contain 4096 32-byte field elements.
        # (32 * 4096) / 2 ** 10 = 128.0 -> Each BLOB can store up to 128kb.
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
            "data": f"0x{sig}{encoded}",
        }

        signed = a0.sign_transaction(tx, blobs=[blob_data] * num_blobs)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        transaction = w3.eth.get_transaction(tx_hash)

        # sanity check
        assert len(transaction["blobVersionedHashes"]) == num_blobs
        for i in range(num_blobs):
            assert transaction["blobVersionedHashes"][i] == HexBytes(expected_versioned_hash)

    c.set_blobhash(0)
    assert c.x() == b"\x00" * 32

    _send_tx_with_blobs(1, 0)
    assert "0x" + c.x().hex() == expected_versioned_hash

    _send_tx_with_blobs(6, 5)
    assert "0x" + c.x().hex() == expected_versioned_hash

    _send_tx_with_blobs(1, 1)
    assert c.x() == b"\x00" * 32
