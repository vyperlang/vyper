#!/usr/bin/env python3

import pytest

from vyper.cli.vyper_json import get_input_dict_settings
from vyper.evm.opcodes import DEFAULT_EVM_VERSION
from vyper.exceptions import JSONError


def test_unknown_evm():
    with pytest.raises(JSONError):
        get_input_dict_settings({"settings": {"evmVersion": "foo"}})


@pytest.mark.parametrize("evm_version", ["homestead", "tangerineWhistle", "spuriousDragon"])
def test_early_evm(evm_version):
    with pytest.raises(JSONError):
        get_input_dict_settings({"settings": {"evmVersion": evm_version}})


@pytest.mark.parametrize("evm_version", ["byzantium", "constantinople", "petersburg"])
def test_valid_evm(evm_version):
    settings = get_input_dict_settings({"settings": {"evmVersion": evm_version}})
    assert settings == {"evm_version": evm_version}


def test_default_evm():
    get_input_dict_settings({}) == {"evm_version": DEFAULT_EVM_VERSION}
