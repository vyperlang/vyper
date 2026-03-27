import pytest

from tests.evm_backends.abi import abi_decode
from tests.evm_backends.base_env import ExecutionReverted
from vyper.utils import method_id


def test_custom_error_revert(env, get_contract):
    code = """
error Unauthorized:
    caller: address

@external
def fail():
    raise Unauthorized(caller=msg.sender)
    """

    contract = get_contract(code)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.fail(sender=env.deployer)

    revert_hex = excinfo.value.args[0]
    assert revert_hex.startswith("0x")

    data = bytes.fromhex(revert_hex[2:])
    assert data[:4] == method_id("Unauthorized(address)")

    (caller,) = abi_decode("(address)", data[4:])
    assert caller == env.deployer


def test_custom_error_dynamic_arg(env, get_contract):
    code = """
error Fancy:
    note: String[16]
    count: uint256

@external
def boom():
    raise Fancy(note="hi", count=3)
    """

    contract = get_contract(code)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.boom(sender=env.deployer)

    data = bytes.fromhex(excinfo.value.args[0][2:])
    assert data[:4] == method_id("Fancy(string,uint256)")

    decoded = abi_decode("(string,uint256)", data[4:])
    assert decoded == ("hi", 3)
