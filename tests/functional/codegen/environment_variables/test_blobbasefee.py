import pytest
from eth.vm.forks.cancun.constants import BLOB_BASE_FEE_UPDATE_FRACTION, MIN_BLOB_BASE_FEE
from eth.vm.forks.cancun.state import fake_exponential


@pytest.mark.requires_evm_version("cancun")
def test_blobbasefee(env, get_contract):
    code = """
@external
@view
def get_blobbasefee() -> uint256:
    return block.blobbasefee
"""
    c = get_contract(code)

    assert c.get_blobbasefee() == MIN_BLOB_BASE_FEE

    env.set_balance(env.deployer, 10**20)
    env.set_excess_blob_gas(10**6)

    # kzg_hash(b"Vyper is the language of the sneks")
    env.blob_hashes = [
        (bytes.fromhex("015a5c97e3cc516f22a95faf7eefff00eb2fee7a65037fde07ac5446fc93f2a0"))
    ] * 6

    env.message_call(
        "0xb45BEc6eeCA2a09f4689Dd308F550Ad7855051B5",  # random address
        gas=21000,
        gas_price=10**10,
    )

    excess_blob_gas = env.get_excess_blob_gas()
    expected_blobbasefee = fake_exponential(
        MIN_BLOB_BASE_FEE, excess_blob_gas, BLOB_BASE_FEE_UPDATE_FRACTION
    )
    assert c.get_blobbasefee() == expected_blobbasefee
