import pytest

from vyper.compiler import compile_code
from vyper.evm.opcodes import EVM_VERSIONS
from vyper.exceptions import StructureException

post_cancun = {k: v for k, v in EVM_VERSIONS.items() if v >= EVM_VERSIONS["cancun"]}


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS.keys()))
def test_transient_blocked(evm_version):
    # test transient is blocked on pre-cancun and compiles post-cancun
    code = """
my_map: transient(HashMap[address, uint256])
    """
    if EVM_VERSIONS[evm_version] >= EVM_VERSIONS["cancun"]:
        assert compile_code(code, evm_version=evm_version) is not None
    else:
        with pytest.raises(StructureException):
            compile_code(code, evm_version=evm_version)


@pytest.mark.parametrize("evm_version", list(post_cancun.keys()))
def test_transient_compiles(evm_version):
    # test transient keyword at least generates TLOAD/TSTORE opcodes
    getter_code = """
my_map: public(transient(HashMap[address, uint256]))
    """
    t = compile_code(getter_code, evm_version=evm_version, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" in t
    assert "TSTORE" not in t

    setter_code = """
my_map: transient(HashMap[address, uint256])

@external
def setter(k: address, v: uint256):
    self.my_map[k] = v
    """
    t = compile_code(setter_code, evm_version=evm_version, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" not in t
    assert "TSTORE" in t

    getter_setter_code = """
my_map: public(transient(HashMap[address, uint256]))

@external
def setter(k: address, v: uint256):
    self.my_map[k] = v
    """
    t = compile_code(
        getter_setter_code, evm_version=evm_version, output_formats=["opcodes_runtime"]
    )
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" in t
    assert "TSTORE" in t
