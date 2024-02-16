from decimal import Decimal

import pytest
from eth.codecs import abi
from eth_utils import keccak

from vyper.evm.opcodes import EVM_VERSIONS
from vyper.utils import int_bounds


def _make_tx(w3, address, signature, values):
    # helper function to broadcast transactions that fail clamping check
    sig = keccak(signature.encode()).hex()[:8]
    data = "".join(int(i).to_bytes(32, "big", signed=i < 0).hex() for i in values)
    w3.eth.send_transaction({"to": address, "data": f"0x{sig}{data}"})


def _make_abi_encode_tx(w3, address, signature, input_types, values):
    # helper function to broadcast transactions where data is constructed from abi_encode
    sig = keccak(signature.encode()).hex()[:8]
    data = abi.encode(input_types, values).hex()
    w3.eth.send_transaction({"to": address, "data": f"0x{sig}{data}"})


def _make_dynarray_data(offset, length, values):
    input = [offset] + [length] + values
    data = "".join(int(i).to_bytes(32, "big", signed=i < 0).hex() for i in input)
    return data


def _make_invalid_dynarray_tx(w3, address, signature, data):
    sig = keccak(signature.encode()).hex()[:8]
    w3.eth.send_transaction({"to": address, "data": f"0x{sig}{data}"})


def test_bytes_clamper(tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
@external
def foo(s: Bytes[3]) -> Bytes[3]:
    return s
    """

    c = get_contract_with_gas_estimation(clamper_test_code)
    assert c.foo(b"ca") == b"ca"
    assert c.foo(b"cat") == b"cat"
    with tx_failed():
        c.foo(b"cate")


def test_bytes_clamper_multiple_slots(tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
@external
def foo(s: Bytes[40]) -> Bytes[40]:
    return s
    """

    data = b"this is exactly forty characters long!!!"
    c = get_contract_with_gas_estimation(clamper_test_code)

    assert c.foo(data[:30]) == data[:30]
    assert c.foo(data) == data
    with tx_failed():
        c.foo(data + b"!")


def test_bytes_clamper_on_init(tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
foo: Bytes[3]

@deploy
def __init__(x: Bytes[3]):
    self.foo = x

@external
def get_foo() -> Bytes[3]:
    return self.foo
    """

    c = get_contract_with_gas_estimation(clamper_test_code, *[b"cat"])
    assert c.get_foo() == b"cat"

    with tx_failed():
        get_contract_with_gas_estimation(clamper_test_code, *[b"cats"])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("n", list(range(1, 33)))
def test_bytes_m_clamper_passing(w3, get_contract, n, evm_version):
    values = [b"\xff" * (i + 1) for i in range(n)]

    code = f"""
@external
def foo(s: bytes{n}) -> bytes{n}:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    for v in values:
        v = v.ljust(n, b"\x00")
        assert c.foo(v) == v


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("n", list(range(1, 32)))  # bytes32 always passes
def test_bytes_m_clamper_failing(w3, get_contract, tx_failed, n, evm_version):
    values = []
    values.append(b"\x00" * n + b"\x80")  # just one bit set
    values.append(b"\xff" * n + b"\x80")  # n*8 + 1 bits set
    values.append(b"\x00" * 31 + b"\x01")  # bytes32
    values.append(b"\xff" * 32)  # bytes32
    values.append(bytes(range(32)))  # 0x00010203..1f
    values.append(bytes(range(1, 33)))  # 0x01020304..a0
    values.append(b"\xff" * 32)

    code = f"""
@external
def foo(s: bytes{n}) -> bytes{n}:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    for v in values:
        # munge for `_make_tx`
        with tx_failed():
            int_value = int.from_bytes(v, byteorder="big")
            _make_tx(w3, c.address, f"foo(bytes{n})", [int_value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("n", list(range(32)))
def test_sint_clamper_passing(w3, get_contract, n, evm_version):
    bits = 8 * (n + 1)
    lo, hi = int_bounds(True, bits)
    values = [-1, 0, 1, lo, hi]
    code = f"""
@external
def foo(s: int{bits}) -> int{bits}:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    for v in values:
        assert c.foo(v) == v


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("n", list(range(31)))  # int256 does not clamp
def test_sint_clamper_failing(w3, tx_failed, get_contract, n, evm_version):
    bits = 8 * (n + 1)
    lo, hi = int_bounds(True, bits)
    values = [-(2**255), 2**255 - 1, lo - 1, hi + 1]
    code = f"""
@external
def foo(s: int{bits}) -> int{bits}:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    for v in values:
        with tx_failed():
            _make_tx(w3, c.address, f"foo(int{bits})", [v])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [True, False])
def test_bool_clamper_passing(w3, get_contract, value, evm_version):
    code = """
@external
def foo(s: bool) -> bool:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    assert c.foo(value) == value


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [2, 3, 4, 8, 16, 2**256 - 1])
def test_bool_clamper_failing(w3, tx_failed, get_contract, value, evm_version):
    code = """
@external
def foo(s: bool) -> bool:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    with tx_failed():
        _make_tx(w3, c.address, "foo(bool)", [value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [0] + [2**i for i in range(5)])
def test_flag_clamper_passing(w3, get_contract, value, evm_version):
    code = """
flag Roles:
    USER
    STAFF
    ADMIN
    MANAGER
    CEO

@external
def foo(s: Roles) -> Roles:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    assert c.foo(value) == value


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [2**i for i in range(5, 256)])
def test_flag_clamper_failing(w3, tx_failed, get_contract, value, evm_version):
    code = """
flag Roles:
    USER
    STAFF
    ADMIN
    MANAGER
    CEO

@external
def foo(s: Roles) -> Roles:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    with tx_failed():
        _make_tx(w3, c.address, "foo(uint256)", [value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("n", list(range(32)))
def test_uint_clamper_passing(w3, get_contract, evm_version, n):
    bits = 8 * (n + 1)
    values = [0, 1, 2**bits - 1]
    code = f"""
@external
def foo(s: uint{bits}) -> uint{bits}:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    for v in values:
        assert c.foo(v) == v


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("n", list(range(31)))  # uint256 has no failing cases
def test_uint_clamper_failing(w3, tx_failed, get_contract, evm_version, n):
    bits = 8 * (n + 1)
    values = [-1, -(2**255), 2**bits]
    code = f"""
@external
def foo(s: uint{bits}) -> uint{bits}:
    return s
    """
    c = get_contract(code, evm_version=evm_version)
    for v in values:
        with tx_failed():
            _make_tx(w3, c.address, f"foo(uint{bits})", [v])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize(
    "value,expected",
    [
        ("0x0000000000000000000000000000000000000000", None),
        (
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000001",
        ),
        (
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
        ),
    ],
)
def test_address_clamper_passing(w3, get_contract, value, expected, evm_version):
    code = """
@external
def foo(s: address) -> address:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    assert c.foo(value) == expected


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize("value", [2**160, 2**256 - 1])
def test_address_clamper_failing(w3, tx_failed, get_contract, value, evm_version):
    code = """
@external
def foo(s: address) -> address:
    return s
    """

    c = get_contract(code, evm_version=evm_version)
    with tx_failed():
        _make_tx(w3, c.address, "foo(address)", [value])


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize(
    "value",
    [
        0,
        1,
        -1,
        Decimal(2**167 - 1) / 10**10,
        -Decimal(2**167) / 10**10,
        "0.0",
        "1.0",
        "-1.0",
        "0.0000000001",
        "0.9999999999",
        "-0.0000000001",
        "-0.9999999999",
        "18707220957835557353007165858768422651595.9365500927",  # 2**167 - 1e-10
        "-18707220957835557353007165858768422651595.9365500928",  # -2**167
    ],
)
def test_decimal_clamper_passing(get_contract, value, evm_version):
    code = """
@external
def foo(s: decimal) -> decimal:
    return s
    """

    c = get_contract(code, evm_version=evm_version)

    assert c.foo(Decimal(value)) == Decimal(value)


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
@pytest.mark.parametrize(
    "value",
    [
        2**167,
        -(2**167 + 1),
        187072209578355573530071658587684226515959365500928,  # 2 ** 167
        -187072209578355573530071658587684226515959365500929,  # - (2 ** 127 - 1e-10)
    ],
)
def test_decimal_clamper_failing(w3, tx_failed, get_contract, value, evm_version):
    code = """
@external
def foo(s: decimal) -> decimal:
    return s
    """

    c = get_contract(code, evm_version=evm_version)

    with tx_failed():
        _make_tx(w3, c.address, "foo(fixed168x10)", [value])


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_int128_array_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(a: uint256, b: int128[5], c: uint256) -> int128[5]:
    return b
    """

    # on both ends of the array we place a `uint256` that would fail the clamp check,
    # to ensure there are no off-by-one errors
    d = [value] * 5
    c = get_contract(code)
    assert c.foo(2**127, [value] * 5, 2**127) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(5))
def test_int128_array_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    # ensure the invalid value is detected at all locations in the array
    code = """
@external
def foo(b: int128[5]) -> int128[5]:
    return b
    """

    values = [0] * 5
    values[idx] = bad_value

    c = get_contract(code)
    with tx_failed():
        _make_tx(w3, c.address, "foo(int128[5])", values)


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_int128_array_looped_clamper_passing(w3, get_contract, value):
    # when an array is > 5 items, the arg clamper runs in a loop to reduce bytecode size
    code = """
@external
def foo(a: uint256, b: int128[10], c: uint256) -> int128[10]:
    return b
    """

    d = [value] * 10
    c = get_contract(code)
    assert c.foo(2**127, d, 2**127) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(10))
def test_int128_array_looped_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    code = """
@external
def foo(b: int128[10]) -> int128[10]:
    return b
    """

    values = [0] * 10
    values[idx] = bad_value

    c = get_contract(code)
    with tx_failed():
        _make_tx(w3, c.address, "foo(int128[10])", values)


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_multidimension_array_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(a: uint256, b: int128[6][3][1][8], c: uint256) -> int128[6][3][1][8]:
    return b
    """

    # 6 * 3 * 1 * 8 = 144, the total number of values in our multidimensional array
    d = [[[[value] * 6] * 3] * 1] * 8
    c = get_contract(code)
    assert c.foo(2**127, d, 2**127, call={"gasPrice": 0}) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(12))
def test_multidimension_array_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    code = """
@external
def foo(b: int128[6][1][2]) -> int128[6][1][2]:
    return b
    """

    values = [0] * 12
    values[idx] = bad_value

    c = get_contract(code)
    with tx_failed():
        _make_tx(w3, c.address, "foo(int128[6][1][2]])", values)


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_int128_dynarray_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(a: uint256, b: DynArray[int128, 5], c: uint256) -> DynArray[int128, 5]:
    return b
    """

    # on both ends of the array we place a `uint256` that would fail the clamp check,
    # to ensure there are no off-by-one errors
    d = [value] * 5
    c = get_contract(code)
    assert c.foo(2**127, d, 2**127) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(5))
def test_int128_dynarray_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    # ensure the invalid value is detected at all locations in the array
    code = """
@external
def foo(b: int128[5]) -> int128[5]:
    return b
    """

    values = [0] * 5
    values[idx] = bad_value
    signature = "foo(int128[])"

    c = get_contract(code)

    data = _make_dynarray_data(32, 5, values)
    with tx_failed():
        _make_invalid_dynarray_tx(w3, c.address, signature, data)


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_int128_dynarray_looped_clamper_passing(w3, get_contract, value):
    # when an array is > 5 items, the arg clamper runs in a loop to reduce bytecode size
    code = """
@external
def foo(a: uint256, b: DynArray[int128, 10], c: uint256) -> DynArray[int128, 10]:
    return b
    """
    d = [value] * 10
    c = get_contract(code)
    assert c.foo(2**127, d, 2**127) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(10))
def test_int128_dynarray_looped_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    code = """
@external
def foo(b: DynArray[int128, 10]) -> DynArray[int128, 10]:
    return b
    """

    values = [0] * 10
    values[idx] = bad_value

    c = get_contract(code)

    data = _make_dynarray_data(32, 10, values)
    signature = "foo(int128[])"
    with tx_failed():
        _make_invalid_dynarray_tx(w3, c.address, signature, data)


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_multidimension_dynarray_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(
    a: uint256,
    b: DynArray[DynArray[DynArray[DynArray[int128, 5], 6], 7], 8],
    c: uint256
) -> DynArray[DynArray[DynArray[DynArray[int128, 5], 6], 7], 8]:
    return b
    """
    # Out of gas exception if outermost length is 6 and greater
    d = [[[[value] * 5] * 6] * 7] * 8
    c = get_contract(code)
    assert c.foo(2**127, d, 2**127, call={"gasPrice": 0}) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(4))
def test_multidimension_dynarray_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    code = """
@external
def foo(b: DynArray[DynArray[int128, 2], 2]) -> DynArray[DynArray[int128, 2], 2]:
    return b
    """

    values = [[0] * 2] * 2
    values[idx // 2][idx % 2] = bad_value

    data = _make_dynarray_data(32, 2, [64, 160])  # Offset of nested arrays
    for v in values:
        # Length of 2
        v = [2] + v
        inner_data = "".join(int(_v).to_bytes(32, "big", signed=_v < 0).hex() for _v in v)
        data += inner_data

    signature = "foo(int128[][])"

    c = get_contract(code)
    with tx_failed():
        _make_invalid_dynarray_tx(w3, c.address, signature, data)


@pytest.mark.parametrize("value", [0, 1, -1, 2**127 - 1, -(2**127)])
def test_dynarray_list_clamper_passing(w3, get_contract, value):
    code = """
@external
def foo(
    a: uint256,
    b: DynArray[int128[5], 6],
    c: uint256
) -> DynArray[int128[5], 6]:
    return b
    """
    d = [[value] * 5] * 6
    c = get_contract(code)
    assert c.foo(2**127, d, 2**127) == d


@pytest.mark.parametrize("bad_value", [2**127, -(2**127) - 1, 2**255 - 1, -(2**255)])
@pytest.mark.parametrize("idx", range(10))
def test_dynarray_list_clamper_failing(w3, tx_failed, get_contract, bad_value, idx):
    # ensure the invalid value is detected at all locations in the array
    code = """
@external
def foo(b: DynArray[int128[5], 2]) -> DynArray[int128[5], 2]:
    return b
    """

    values = [[0] * 5, [0] * 5]
    values[idx // 5][idx % 5] = bad_value

    data = _make_dynarray_data(32, 2, [])  # Offset of nested arrays
    for v in values:
        inner_data = "".join(int(_v).to_bytes(32, "big", signed=_v < 0).hex() for _v in v)
        data += inner_data

    c = get_contract(code)
    signature = "foo(int128[5][])"
    with tx_failed():
        _make_invalid_dynarray_tx(w3, c.address, signature, data)
