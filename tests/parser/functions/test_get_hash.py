
import pytest

from vyper.compiler import (
    compile_code,
)
from vyper.exceptions import (
    EvmVersionException,
)
from vyper.opcodes import (
    EVM_VERSIONS,
)
from vyper.utils import (
    keccak256,
)


@pytest.mark.parametrize('evm_version', list(EVM_VERSIONS))
def test_get_extcodehash(get_contract, evm_version):
    code = """
a: address

@public
def __init__():
    self.a = self

@public
def foo(x: address) -> bytes32:
    return get_extcodehash(x)

@public
def foo2(x: address) -> bytes32:
    b: address = x
    return get_extcodehash(b)

@public
def foo3() -> bytes32:
    return get_extcodehash(self)

@public
def foo4() -> bytes32:
    return get_extcodehash(self.a)
    """

    if evm_version in ("byzantium", "atlantis"):
        with pytest.raises(EvmVersionException):
            compile_code(code, evm_version=evm_version)
        return

    compiled = compile_code(code, ['bytecode_runtime'], evm_version=evm_version)
    bytecode = bytes.fromhex(compiled['bytecode_runtime'][2:])
    hash_ = keccak256(bytecode)

    c = get_contract(code, evm_version=evm_version)

    assert c.foo(c.address) == hash_
    assert not int(c.foo("0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF").hex(), 16)

    assert c.foo2(c.address) == hash_
    assert not int(c.foo2("0xDeaDbeefdEAdbeefdEadbEEFdeadbeEFdEaDbeeF").hex(), 16)

    assert c.foo3() == hash_
    assert c.foo4() == hash_
