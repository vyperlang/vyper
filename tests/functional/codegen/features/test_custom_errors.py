import pytest

from tests.evm_backends.abi import abi_decode
from tests.evm_backends.base_env import ExecutionReverted
from vyper.compiler.settings import Settings
from vyper.utils import method_id


def _deploy(get_contract, source_code, use_experimental_codegen):
    settings = Settings(experimental_codegen=use_experimental_codegen)
    return get_contract(source_code, compiler_settings=settings)


def _revert_data(excinfo):
    revert_hex = excinfo.value.args[0]
    assert revert_hex.startswith("0x")
    return bytes.fromhex(revert_hex[2:])


@pytest.mark.parametrize("use_experimental_codegen", [False, True])
def test_custom_error_raise_encodes_static_arg(env, get_contract, use_experimental_codegen):
    code = """
error Unauthorized:
    caller: address

@external
def fail():
    raise Unauthorized(caller=msg.sender)
    """

    contract = _deploy(get_contract, code, use_experimental_codegen)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.fail(sender=env.deployer)

    data = _revert_data(excinfo)
    assert data[:4] == method_id("Unauthorized(address)")
    assert abi_decode("(address)", data[4:]) == (env.deployer,)


@pytest.mark.parametrize("use_experimental_codegen", [False, True])
def test_custom_error_assert_encodes_arg_on_failure(env, get_contract, use_experimental_codegen):
    code = """
error Unauthorized:
    caller: address

@external
def fail(x: uint256):
    assert x > 0, Unauthorized(caller=msg.sender)
    """

    contract = _deploy(get_contract, code, use_experimental_codegen)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.fail(0, sender=env.deployer)

    data = _revert_data(excinfo)
    assert data[:4] == method_id("Unauthorized(address)")
    assert abi_decode("(address)", data[4:]) == (env.deployer,)


@pytest.mark.parametrize("use_experimental_codegen", [False, True])
def test_custom_error_assert_does_not_revert_on_success(get_contract, use_experimental_codegen):
    code = """
error Unauthorized:
    caller: address

@external
def fail(x: uint256):
    assert x > 0, Unauthorized(caller=msg.sender)
    """

    contract = _deploy(get_contract, code, use_experimental_codegen)
    contract.fail(1)


@pytest.mark.parametrize("use_experimental_codegen", [False, True])
def test_custom_error_zero_arg_reverts_with_selector_only(get_contract, use_experimental_codegen):
    code = """
error Simple:
    pass

@external
def fail():
    raise Simple()
    """

    contract = _deploy(get_contract, code, use_experimental_codegen)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.fail()

    assert _revert_data(excinfo) == method_id("Simple()")


@pytest.mark.parametrize("use_experimental_codegen", [False, True])
def test_custom_error_keyword_encoding_uses_declaration_order(
    get_contract, use_experimental_codegen
):
    code = """
error Ordered:
    a: uint256
    b: uint256

@external
def boom():
    raise Ordered(a=1, b=2)
    """

    contract = _deploy(get_contract, code, use_experimental_codegen)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.boom()

    data = _revert_data(excinfo)
    assert data[:4] == method_id("Ordered(uint256,uint256)")
    assert abi_decode("(uint256,uint256)", data[4:]) == (1, 2)


@pytest.mark.parametrize("use_experimental_codegen", [False, True])
def test_custom_error_dynamic_arg_encoding(get_contract, use_experimental_codegen):
    code = """
error Fancy:
    note: String[16]
    count: uint256

@external
def boom():
    raise Fancy(note="hi", count=3)
    """

    contract = _deploy(get_contract, code, use_experimental_codegen)

    with pytest.raises(ExecutionReverted) as excinfo:
        contract.boom()

    data = _revert_data(excinfo)
    assert data[:4] == method_id("Fancy(string,uint256)")
    assert abi_decode("(string,uint256)", data[4:]) == ("hi", 3)
