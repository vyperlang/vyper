import pytest

from vyper import compiler
from vyper.evm.opcodes import EVM_VERSIONS


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
def test_self_balance(w3, get_contract_with_gas_estimation, evm_version):
    code = """
@external
@view
def get_balance() -> uint256:
    a: uint256 = self.balance
    return a

@external
@payable
def __default__():
    pass
    """
    opcodes = compiler.compile_code(code, ["opcodes"], evm_version=evm_version)["opcodes"]
    if EVM_VERSIONS[evm_version] >= EVM_VERSIONS["istanbul"]:
        assert "SELFBALANCE" in opcodes
    else:
        assert "SELFBALANCE" not in opcodes

    c = get_contract_with_gas_estimation(code, evm_version=evm_version)
    w3.eth.send_transaction({"to": c.address, "value": 1337})

    assert c.get_balance() == 1337
