import pytest

from vyper.compiler import compile_code
from vyper.evm.opcodes import version_check
from vyper.exceptions import StructureException


def test_transient_blocked(evm_version):
    # test transient is blocked on pre-cancun and compiles post-cancun
    code = """
my_map: transient(HashMap[address, uint256])
    """
    if version_check(begin="cancun"):
        assert compile_code(code) is not None
    else:
        with pytest.raises(StructureException):
            compile_code(code)


def test_transient_compiles():
    if not version_check(begin="cancun"):
        return

    getter_code = """
my_map: public(transient(HashMap[address, uint256]))
    """
    t = compile_code(getter_code, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" in t
    assert "TSTORE" not in t

    setter_code = """
my_map: transient(HashMap[address, uint256])

@external
def setter(k: address, v: uint256):
    self.my_map[k] = v
    """
    t = compile_code(setter_code, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" not in t
    assert "TSTORE" in t

    getter_setter_code = """
my_map: public(transient(HashMap[address, uint256]))

@external
def setter(k: address, v: uint256):
    self.my_map[k] = v
    """
    t = compile_code(getter_setter_code, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" in t
    assert "TSTORE" in t
