import pytest

from vyper.opcodes import (
    EVM_VERSIONS,
)


@pytest.mark.parametrize('evm_version', list(EVM_VERSIONS))
def test_self_balance(w3, get_contract_with_gas_estimation, evm_version):
    code = """
@public
@constant
def get_balance() -> uint256:
    a: uint256 = self.balance
    return a

@public
@payable
def __default__():
    pass
    """
    c = get_contract_with_gas_estimation(code, evm_version=evm_version)

    if evm_version == "istanbul":
        assert 0x47 in c._classic_contract.bytecode
    else:
        assert 0x47 not in c._classic_contract.bytecode

    w3.eth.sendTransaction({'to': c.address, 'value': 1337})
    assert c.get_balance() == 1337
