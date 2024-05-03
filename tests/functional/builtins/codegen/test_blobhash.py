import pytest

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
def test_get_blobhashes(env, get_contract, tx_failed):
    code = """
x: public(bytes32)
@external
def set_blobhash(i: uint256):
    self.x = blobhash(i)
"""
    c = get_contract(code)

    # to get the expected versioned hashes:
    #
    # from eth_account._utils.typed_transactions import BlobTransaction
    # blob_transaction = BlobTransaction.from_bytes(HexBytes(signed.rawTransaction))
    # print(blob_transaction.blob_data.versioned_hashes)
    expected_versioned_hash = "0x0168dea5bd14ec82691edc861dcee360342a921c1664b02745465f6c42239f06"

    def _send_tx_with_blobs(num_blobs, input_idx):
        env.blob_hashes = [bytes.fromhex(expected_versioned_hash[2:])] * num_blobs
        c.set_blobhash(input_idx)

    c.set_blobhash(0)
    assert c.x() == b"\x00" * 32

    _send_tx_with_blobs(1, 0)
    assert "0x" + c.x().hex() == expected_versioned_hash

    _send_tx_with_blobs(6, 5)
    assert "0x" + c.x().hex() == expected_versioned_hash

    _send_tx_with_blobs(1, 1)
    assert c.x() == b"\x00" * 32
