#!/usr/bin/env python3

import pytest

from vyper.cli.vyper_json import get_evm_version
from vyper.evm.opcodes import DEFAULT_EVM_VERSION
from vyper.exceptions import JSONError


def test_unknown_evm():
    with pytest.raises(JSONError):
        get_evm_version({"settings": {"evmVersion": "foo"}})


@pytest.mark.parametrize("evm_version", ["homestead", "tangerineWhistle", "spuriousDragon"])
def test_early_evm(evm_version):
    with pytest.raises(JSONError):
        get_evm_version({"settings": {"evmVersion": evm_version}})


@pytest.mark.parametrize("evm_version", ["byzantium", "constantinople", "petersburg"])
def test_valid_evm(evm_version):
    assert evm_version == get_evm_version({"settings": {"evmVersion": evm_version}})


def test_default_evm():
    assert get_evm_version({}) == DEFAULT_EVM_VERSION
