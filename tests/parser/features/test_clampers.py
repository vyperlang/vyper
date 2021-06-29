import pytest
from eth_utils import keccak

from vyper.evm.opcodes import EVM_VERSIONS


def _make_tx(w3, address, signature, values):
    # helper function to broadcast transactions that fail clamping check
    sig = keccak(signature.encode()).hex()[:8]
    data = "".join(int(i).to_bytes(32, "big", signed=i < 0).hex() for i in values)
    w3.eth.sendTransaction({"to": address, "data": f"0x{sig}{data}"})


def test_bytes_clamper(assert_tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
@external
def foo(s: Bytes[3]) -> Bytes[3]:
    return s
    """

    c = get_contract_with_gas_estimation(clamper_test_code)
    assert c.foo(b"ca") == b"ca"
    assert c.foo(b"cat") == b"cat"
    assert_tx_failed(lambda: c.foo(b"cate"))


def test_bytes_clamper_multiple_slots(assert_tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
@external
def foo(s: Bytes[40]) -> Bytes[40]:
    return s
    """

    data = b"this is exactly forty characters long!!!"
    c = get_contract_with_gas_estimation(clamper_test_code)

    assert c.foo(data[:30]) == data[:30]
    assert c.foo(data) == data
    assert_tx_failed(lambda: c.foo(data + b"!"))


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_int128_clamper_passing(w3, get_contract, value, evm_version):
    code = """
@external
def foo(s: int128) -> int128:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    _make_tx(w3, c.address, "foo(int128)", [value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
def test_int128_clamper_failing(w3, assert_tx_failed, get_contract, value, evm_version):
    code = """
@external
def foo(s: int128) -> int128:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    assert_tx_failed(lambda: _make_tx(w3, c.address, "foo(int128)", [value]))


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [0, 1])
def test_bool_clamper_passing(w3, get_contract, value, evm_version):
    code = """
@external
def foo(s: bool) -> bool:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    _make_tx(w3, c.address, "foo(bool)", [value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [2, 3, 4, 8, 16, 2 ** 256 - 1])
def test_bool_clamper_failing(w3, assert_tx_failed, get_contract, value, evm_version):
    code = """
@external
def foo(s: bool) -> bool:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    assert_tx_failed(lambda: _make_tx(w3, c.address, "foo(bool)", [value]))


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [0, 1, 2 ** 160 - 1])
def test_address_clamper_passing(w3, get_contract, value, evm_version):
    code = """
@external
def foo(s: address) -> address:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    _make_tx(w3, c.address, "foo(address)", [value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [2 ** 160, 2 ** 256 - 1])
def test_address_clamper_failing(w3, assert_tx_failed, get_contract, value, evm_version):
    code = """
@external
def foo(s: address) -> address:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    assert_tx_failed(lambda: _make_tx(w3, c.address, "foo(address)", [value]))


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_int128_array_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(a: uint256, b: int128[5], c: uint256) -> int128[5]:
    return b
    """

    # on both ends of the array we place a `uint256` that would fail the clamp check,
    # to ensure there are no off-by-one errors
    values = [2 ** 127] + ([value] * 5) + [2 ** 127]

    c = get_contract(code)
    _make_tx(w3, c.address, "foo(uint256,int128[5],uint256)", values)


@pytest.mark.parametrize("bad_value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
@pytest.mark.parametrize("idx", range(5))
def test_int128_array_clamper_failing(w3, assert_tx_failed, get_contract, bad_value, idx):
    # ensure the invalid value is detected at all locations in the array
    code = """
@external
def foo(b: int128[5]) -> int128[5]:
    return b
    """

    values = [0] * 5
    values[idx] = bad_value

    c = get_contract(code)
    assert_tx_failed(lambda: _make_tx(w3, c.address, "foo(int128[5])", values))


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_int128_array_looped_clamper_passing(w3, get_contract, value):
    # when an array is > 5 items, the arg clamper runs in a loop to reduce bytecode size
    code = """
@external
def foo(a: uint256, b: int128[10], c: uint256) -> int128[10]:
    return b
    """

    values = [2 ** 127] + ([value] * 10) + [2 ** 127]

    c = get_contract(code)
    _make_tx(w3, c.address, "foo(uint256,int128[10],uint256)", values)


@pytest.mark.parametrize("bad_value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
@pytest.mark.parametrize("idx", range(10))
def test_int128_array_looped_clamper_failing(w3, assert_tx_failed, get_contract, bad_value, idx):
    code = """
@external
def foo(b: int128[10]) -> int128[10]:
    return b
    """

    values = [0] * 10
    values[idx] = bad_value

    c = get_contract(code)
    assert_tx_failed(lambda: _make_tx(w3, c.address, "foo(int128[10])", values))


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_multidimension_array_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(a: uint256, b: int128[6][3][1][8], c: uint256) -> int128[6][3][1][8]:
    return b
    """

    # 6 * 3 * 1 * 8 = 144, the total number of values in our multidimensional array
    values = [2 ** 127] + ([value] * 144) + [2 ** 127]

    c = get_contract(code)
    _make_tx(w3, c.address, "foo(uint256,int128[6][3][1][8],uint256)", values)


@pytest.mark.parametrize("bad_value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
@pytest.mark.parametrize("idx", range(12))
def test_multidimension_array_clamper_failing(w3, assert_tx_failed, get_contract, bad_value, idx):
    code = """
@external
def foo(b: int128[6][1][2]) -> int128[6][1][2]:
    return b
    """

    values = [0] * 12
    values[idx] = bad_value

    c = get_contract(code)
    assert_tx_failed(lambda: _make_tx(w3, c.address, "foo(int128[6][1][2]])", values))
