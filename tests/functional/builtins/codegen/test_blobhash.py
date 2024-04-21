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
def test_get_blobhashes(get_contract_with_gas_estimation, w3):
    code = """
@external
@view
def get_blobhashes() -> bytes32[6]:
    return [blobhash(0), blobhash(1), blobhash(2), blobhash(3), blobhash(4), blobhash(5)]
"""
    c = get_contract_with_gas_estimation(code)

    random_account = w3.eth.account.from_key(f"0x{'00' * 31}01")

    text = b"Long live the BLOBs!"
    # BLOBs contain 4096 32-byte field elements.
    # (32 * 4096) / 2 ** 10 = 128.0 -> Each BLOB can store up to 128kb.
    blob_data = text.rjust(32 * 4096)

    tx = {
        "type": 3,
        "chainId": 1337,
        "from": random_account.address,
        "to": "0xBa5EdBA5eDBA5EdbA5edbA5EDBA5eDbA5edBa5Ed",  # random address
        "value": 0,
        "gas": 21000,
        "maxFeePerGas": 10**10,
        "maxPriorityFeePerGas": 10**10,
        "maxFeePerBlobGas": 10**10,
        "nonce": w3.eth.get_transaction_count(random_account.address),
    }

    signed = random_account.sign_transaction(tx, blobs=[blob_data] * 6)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    tx = w3.eth.get_transaction(tx_hash)

    # the attribute `blobVersionedHashes` are currently only available at the tx-level:
    # https://github.com/ethereum/web3.py/blob/332ff99ae5dbe0209254619801c4848e528f7851/web3/_utils/method_formatters.py#L233
    expected_blob_versioned_hash = tx["blobVersionedHashes"]

    assert c.get_blobhashes() == [expected_blob_versioned_hash for _ in range(6)]
