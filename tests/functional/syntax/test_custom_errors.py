import pytest

from tests.evm_backends.abi import abi_decode
from tests.evm_backends.base_env import ExecutionReverted
from vyper.compiler import compile_code
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


def test_exported_module_custom_error_in_abi(make_input_bundle):
    lib = """
error LibError:
    code: uint256

@external
def fail():
    raise LibError(1)
    """
    main = """
import lib
exports: lib.fail
    """

    input_bundle = make_input_bundle({"lib.vy": lib})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi", "interface"])

    error_abi = next(
        item
        for item in out["abi"]
        if item.get("type") == "error" and item.get("name") == "LibError"
    )
    assert error_abi["inputs"][0]["name"] == "code"
    assert error_abi["inputs"][0]["type"] == "uint256"
    assert "error LibError:" in out["interface"]


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
