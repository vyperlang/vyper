import pytest

from vyper.cli.vyper_json import get_evm_version, get_settings
from vyper.exceptions import JSONError


def test_unknown_evm():
    with pytest.raises(JSONError):
        get_evm_version({"settings": {"evmVersion": "foo"}})


@pytest.mark.parametrize(
    "evm_version_str",
    [
        "homestead",
        "tangerineWhistle",
        "spuriousDragon",
        "byzantium",
        "constantinople",
        "petersburg",
        "istanbul",
        "berlin",
    ],
)
def test_early_evm(evm_version_str):
    with pytest.raises(JSONError):
        get_evm_version({"settings": {"evmVersion": evm_version_str}})


@pytest.mark.parametrize("evm_version_str", ["london", "paris", "shanghai", "cancun", "prague"])
def test_valid_evm(evm_version_str):
    assert evm_version_str == get_evm_version({"settings": {"evmVersion": evm_version_str}})


def test_experimental_codegen_settings():
    input_json = {"settings": {}}
    assert get_settings(input_json).experimental_codegen is None

    input_json = {"settings": {"experimentalCodegen": True}}
    assert get_settings(input_json).experimental_codegen is True

    input_json = {"settings": {"experimentalCodegen": False}}
    assert get_settings(input_json).experimental_codegen is False
