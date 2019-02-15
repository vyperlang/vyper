import pytest
import eth_tester

from vyper import utils as vyper_utils
from vyper.functions.rlp_decoder import get_rlp_decoder_hex


@pytest.fixture(autouse=True)
def patch_large_gas_limit(monkeypatch):
    monkeypatch.setattr(eth_tester.backends.pyevm.main, 'GENESIS_GAS_LIMIT', 10**9)


@pytest.fixture
def fake_tx(tester, w3):
    def fake_tx():
        bytecode = get_rlp_decoder_hex()
        rlp_contract =  w3.eth.contract(bytecode=bytecode, abi=[])
        tx_hash = rlp_contract.constructor().transact()
        tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
        contract_address = tx_receipt.contractAddress
        return contract_address
    return fake_tx
