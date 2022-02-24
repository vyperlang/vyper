from decimal import Decimal

import pytest
from eth_utils import keccak

from vyper.evm.opcodes import EVM_VERSIONS


def _make_tx(w3, address, signature, values):
    # helper function to broadcast transactions that fail clamping check
    sig = keccak(signature.encode()).hex()[:8]
    data = "".join(int(i).to_bytes(32, "big", signed=i < 0).hex() for i in values)
    w3.eth.send_transaction({"to": address, "data": f"0x{sig}{data}"})


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


def test_bytes_clamper_on_init(assert_tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
foo: Bytes[3]

@external
def __init__(x: Bytes[3]):
    self.foo = x

@external
def get_foo() -> Bytes[3]:
    return self.foo
    """

    c = get_contract_with_gas_estimation(clamper_test_code, *[b"cat"])
    assert c.get_foo() == b"cat"

    assert_tx_failed(lambda: get_contract_with_gas_estimation(clamper_test_code, *[b"cats"]))


@pytest.fixture(params=list(EVM_VERSIONS))
def test_int128_clamper_contract(request, get_contract):
    code = """
@external
def foo(s: int128) -> int128:
    return s
    """

    c = get_contract(code, evm_version=request.param)
    return c


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_int128_clamper_passing(w3, test_int128_clamper_contract, value):

    _make_tx(w3, test_int128_clamper_contract.address, "foo(int128)", [value])


@pytest.mark.parametrize("value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
def test_int128_clamper_failing(w3, assert_tx_failed, test_int128_clamper_contract, value):

    assert_tx_failed(
        lambda: _make_tx(w3, test_int128_clamper_contract.address, "foo(int128)", [value])
    )


@pytest.fixture(params=list(EVM_VERSIONS))
def test_bool_clamper_contract(request, get_contract):
    code = """
@external
def foo(s: bool) -> bool:
    return s
    """

    c = get_contract(code, evm_version=request.param)
    return c


@pytest.mark.parametrize("value", [0, 1])
def test_bool_clamper_passing(w3, test_bool_clamper_contract, value):

    _make_tx(w3, test_bool_clamper_contract.address, "foo(bool)", [value])


@pytest.mark.parametrize("value", [2, 3, 4, 8, 16, 2 ** 256 - 1])
def test_bool_clamper_failing(w3, assert_tx_failed, test_bool_clamper_contract, value):

    assert_tx_failed(lambda: _make_tx(w3, test_bool_clamper_contract.address, "foo(bool)", [value]))


@pytest.fixture(params=list(EVM_VERSIONS))
def test_uint8_clamper_contract(request, get_contract):
    code = """
@external
def foo(s: uint8) -> uint8:
    return s
    """

    c = get_contract(code, evm_version=request.param)
    return c


@pytest.mark.parametrize("value", list(range(2 ** 8)))
def test_uint8_clamper_passing(w3, test_uint8_clamper_contract, value):

    _make_tx(w3, test_uint8_clamper_contract.address, "foo(uint8)", [value])


@pytest.mark.parametrize("value", [-100, 256, 2 ** 10, 2 ** 16, 2 ** 32, 2 ** 256 - 1])
def test_uint8_clamper_failing(w3, assert_tx_failed, test_uint8_clamper_contract, value):

    assert_tx_failed(
        lambda: _make_tx(w3, test_uint8_clamper_contract.address, "foo(uint8)", [value])
    )


@pytest.fixture(params=list(EVM_VERSIONS))
def test_address_clamper_contract(request, get_contract):
    code = """
@external
def foo(s: address) -> address:
    return s
    """

    c = get_contract(code, evm_version=request.param)
    return c


@pytest.mark.parametrize("value", [0, 1, 2 ** 160 - 1])
def test_address_clamper_passing(w3, test_address_clamper_contract, value):

    _make_tx(w3, test_address_clamper_contract.address, "foo(address)", [value])


@pytest.mark.parametrize("value", [2 ** 160, 2 ** 256 - 1])
def test_address_clamper_failing(w3, assert_tx_failed, test_address_clamper_contract, value):

    assert_tx_failed(
        lambda: _make_tx(w3, test_address_clamper_contract.address, "foo(address)", [value])
    )


@pytest.fixture(params=list(EVM_VERSIONS))
def test_decimal_clamper_contract(request, get_contract):
    code = """
@external
def foo(s: decimal) -> decimal:
    return s
    """

    c = get_contract(code, evm_version=request.param)
    return c


@pytest.mark.parametrize(
    "value",
    [
        0,
        1,
        -1,
        2 ** 127 - 1,
        -(2 ** 127),
        "0.0",
        "1.0",
        "-1.0",
        "0.0000000001",
        "0.9999999999",
        "-0.0000000001",
        "-0.9999999999",
        "170141183460469231731687303715884105726.9999999999",  # 2 ** 127 - 1.0000000001
        "-170141183460469231731687303715884105727.9999999999",  # - (2 ** 127 - 0.0000000001)
    ],
)
def test_decimal_clamper_passing(test_decimal_clamper_contract, value):

    assert test_decimal_clamper_contract.foo(Decimal(value)) == Decimal(value)


@pytest.mark.parametrize(
    "value",
    [
        2 ** 127,
        -(2 ** 127 + 1),
        "170141183460469231731687303715884105727.0000000001",  # 2 ** 127 - 0.999999999
        "-170141183460469231731687303715884105728.0000000001",  # - (2 ** 127 + 0.0000000001)
    ],
)
def test_decimal_clamper_failing(assert_tx_failed, test_decimal_clamper_contract, value):

    assert_tx_failed(lambda: test_decimal_clamper_contract.foo(Decimal(value)))


@pytest.fixture(params=list(EVM_VERSIONS))
def test_int128_array_clamper_passing_contract(request, get_contract):
    code = """
@external
def foo(a: uint256, b: int128[5], c: uint256) -> int128[5]:
    return b
    """

    c = get_contract(code, evm_version=request.param)
    return c


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_int128_array_clamper_passing(w3, test_int128_array_clamper_passing_contract, value):

    # on both ends of the array we place a `uint256` that would fail the clamp check,
    # to ensure there are no off-by-one errors
    values = [2 ** 127] + ([value] * 5) + [2 ** 127]

    _make_tx(
        w3,
        test_int128_array_clamper_passing_contract.address,
        "foo(uint256,int128[5],uint256)",
        values,
    )


@pytest.fixture
def test_int128_array_clamper_failing_contract(get_contract):
    code = """
@external
def foo(b: int128[5]) -> int128[5]:
    return b
    """

    c = get_contract(code)
    return c


@pytest.mark.parametrize("bad_value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
@pytest.mark.parametrize("idx", range(5))
def test_int128_array_clamper_failing(
    w3, assert_tx_failed, test_int128_array_clamper_failing_contract, bad_value, idx
):
    # ensure the invalid value is detected at all locations in the array
    values = [0] * 5
    values[idx] = bad_value

    assert_tx_failed(
        lambda: _make_tx(
            w3, test_int128_array_clamper_failing_contract.address, "foo(int128[5])", values
        )
    )


@pytest.fixture
def test_int128_array_looped_clamper_passing_contract(get_contract):
    # when an array is > 5 items, the arg clamper runs in a loop to reduce bytecode size
    code = """
@external
def foo(a: uint256, b: int128[10], c: uint256) -> int128[10]:
    return b
    """

    c = get_contract(code)
    return c


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_int128_array_looped_clamper_passing(
    w3, test_int128_array_looped_clamper_passing_contract, value
):

    values = [2 ** 127] + ([value] * 10) + [2 ** 127]
    _make_tx(
        w3,
        test_int128_array_looped_clamper_passing_contract.address,
        "foo(uint256,int128[10],uint256)",
        values,
    )


@pytest.fixture
def test_int128_array_looped_clamper_failing_contract(get_contract):
    code = """
@external
def foo(b: int128[10]) -> int128[10]:
    return b
    """

    c = get_contract(code)
    return c


@pytest.mark.parametrize("bad_value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
@pytest.mark.parametrize("idx", range(10))
def test_int128_array_looped_clamper_failing(
    w3, assert_tx_failed, test_int128_array_looped_clamper_failing_contract, bad_value, idx
):

    values = [0] * 10
    values[idx] = bad_value

    assert_tx_failed(
        lambda: _make_tx(
            w3, test_int128_array_looped_clamper_failing_contract.address, "foo(int128[10])", values
        )
    )


@pytest.fixture
def test_multidimension_array_clamper_passing_contract(get_contract):
    code = """
@external
def foo(a: uint256, b: int128[6][3][1][8], c: uint256) -> int128[6][3][1][8]:
    return b
    """

    c = get_contract(code)
    return c


@pytest.mark.parametrize("value", [0, 1, -1, 2 ** 127 - 1, -(2 ** 127)])
def test_multidimension_array_clamper_passing(
    w3, test_multidimension_array_clamper_passing_contract, value
):
    # 6 * 3 * 1 * 8 = 144, the total number of values in our multidimensional array
    values = [2 ** 127] + ([value] * 144) + [2 ** 127]

    _make_tx(
        w3,
        test_multidimension_array_clamper_passing_contract.address,
        "foo(uint256,int128[6][3][1][8],uint256)",
        values,
    )


@pytest.fixture
def test_multidimension_array_clamper_failing_contract(get_contract):
    code = """
@external
def foo(b: int128[6][1][2]) -> int128[6][1][2]:
    return b
    """

    c = get_contract(code)
    return c


@pytest.mark.parametrize("bad_value", [2 ** 127, -(2 ** 127) - 1, 2 ** 255 - 1, -(2 ** 255)])
@pytest.mark.parametrize("idx", range(12))
def test_multidimension_array_clamper_failing(
    w3, assert_tx_failed, test_multidimension_array_clamper_failing_contract, bad_value, idx
):

    values = [0] * 12
    values[idx] = bad_value

    assert_tx_failed(
        lambda: _make_tx(
            w3,
            test_multidimension_array_clamper_failing_contract.address,
            "foo(int128[6][1][2]])",
            values,
        )
    )
