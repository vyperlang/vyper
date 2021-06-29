import pytest

from vyper.compiler import compile_code
from vyper.evm.opcodes import EVM_VERSIONS

code = """
@external
def _bitwise_and(x: uint256, y: uint256) -> uint256:
    return bitwise_and(x, y)

@external
def _bitwise_or(x: uint256, y: uint256) -> uint256:
    return bitwise_or(x, y)

@external
def _bitwise_xor(x: uint256, y: uint256) -> uint256:
    return bitwise_xor(x, y)

@external
def _bitwise_not(x: uint256) -> uint256:
    return bitwise_not(x)

@external
def _shift(x: uint256, y: int128) -> uint256:
    return shift(x, y)
    """


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
def test_bitwise_opcodes(evm_version):
    opcodes = compile_code(code, ["opcodes"], evm_version=evm_version)["opcodes"]
    if evm_version in ("byzantium", "atlantis"):
        assert "SHL" not in opcodes
        assert "SHR" not in opcodes
    else:
        assert "SHL" in opcodes
        assert "SHR" in opcodes


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
def test_test_bitwise(get_contract_with_gas_estimation, evm_version):
    c = get_contract_with_gas_estimation(code, evm_version=evm_version)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    assert c._bitwise_and(x, y) == (x & y)
    assert c._bitwise_or(x, y) == (x | y)
    assert c._bitwise_xor(x, y) == (x ^ y)
    assert c._bitwise_not(x) == 2 ** 256 - 1 - x
    assert c._shift(x, 3) == x * 8
    assert c._shift(x, 255) == 0
    assert c._shift(y, 255) == 2 ** 255
    assert c._shift(x, 256) == 0
    assert c._shift(x, 0) == x
    assert c._shift(x, -1) == x // 2
    assert c._shift(x, -3) == x // 8
    assert c._shift(x, -256) == 0


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
def test_literals(get_contract, evm_version):
    code = """
@external
def left(x: uint256) -> uint256:
    return shift(x, -3)

@external
def right(x: uint256) -> uint256:
    return shift(x, 3)
    """

    c = get_contract(code, evm_version=evm_version)
    assert c.left(80) == 10
    assert c.right(80) == 640
