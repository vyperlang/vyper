from decimal import Decimal

import pytest

from vyper.exceptions import InvalidType, TypeMismatch
from vyper.utils import checksum_encode


@pytest.fixture
def input_values(request):
    if request.param["in_type"] == "decimal":
        request.param["contract_call_in_value"] = Decimal(request.param["in_value"])
    else:
        request.param["contract_call_in_value"] = request.param["in_value"]
    # request.param["contract_call_in_value"] = request.param["in_value"]
    return request.param


test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"


@pytest.mark.parametrize(
    "input_values",
    [
        {
            "in_type": "bytes32",
            "out_type": "address",
            "in_value": int(test_address, 16).to_bytes(20, "big").rjust(32, b"\00"),
            "out_value": test_address,
        },  # Bug with state variables,
        {
            "in_type": "uint256",
            "out_type": "address",
            "in_value": int(test_address, 16),
            "out_value": test_address,
        },
        {"in_type": "decimal", "out_type": "bool", "in_value": 0.0, "out_value": False},
        {"in_type": "decimal", "out_type": "bool", "in_value": -0.1, "out_value": True},
        {"in_type": "decimal", "out_type": "bool", "in_value": 100.0, "out_value": True},
        {"in_type": "uint8", "out_type": "bool", "in_value": 0, "out_value": False},
        {"in_type": "uint8", "out_type": "bool", "in_value": 1, "out_value": True},
        {"in_type": "uint8", "out_type": "bool", "in_value": 2 ** 8 - 1, "out_value": True},
        {"in_type": "int128", "out_type": "bool", "in_value": 0, "out_value": False},
        {"in_type": "int128", "out_type": "bool", "in_value": 1, "out_value": True},
        {"in_type": "int128", "out_type": "bool", "in_value": 2 ** 127 - 1, "out_value": True},
        {"in_type": "int128", "out_type": "bool", "in_value": -1, "out_value": True},
        {"in_type": "int128", "out_type": "bool", "in_value": -(2 ** 127), "out_value": True},
        {"in_type": "uint256", "out_type": "bool", "in_value": 0, "out_value": False},
        {"in_type": "uint256", "out_type": "bool", "in_value": 1, "out_value": True},
        {"in_type": "uint256", "out_type": "bool", "in_value": 2 ** 256 - 1, "out_value": True},
        {"in_type": "int256", "out_type": "bool", "in_value": 0, "out_value": False},
        {"in_type": "int256", "out_type": "bool", "in_value": 1, "out_value": True},
        {"in_type": "int256", "out_type": "bool", "in_value": 2 ** 255 - 1, "out_value": True},
        {"in_type": "int256", "out_type": "bool", "in_value": -1, "out_value": True},
        {"in_type": "int256", "out_type": "bool", "in_value": -(2 ** 255), "out_value": True},
        {
            "in_type": "bytes32",
            "out_type": "bool",
            "in_value": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "out_value": False,
        },
        {
            "in_type": "bytes32",
            "out_type": "bool",
            "in_value": "0x000000000FFF0000000000000000000000000000FF0000000000000000000FFF",
            "out_value": True,
        },
        {"in_type": "Bytes[32]", "out_type": "bool", "in_value": b"", "out_value": False},
        {"in_type": "Bytes[32]", "out_type": "bool", "in_value": b"\x00", "out_value": False},
        {"in_type": "Bytes[32]", "out_type": "bool", "in_value": b"\x00" * 32, "out_value": False},
        {"in_type": "Bytes[32]", "out_type": "bool", "in_value": b"\x01", "out_value": True},
        {"in_type": "Bytes[32]", "out_type": "bool", "in_value": b"\x00\x01", "out_value": True},
        {
            "in_type": "Bytes[32]",
            "out_type": "bool",
            "in_value": b"\x01\x00\x00\x00\x01",
            "out_value": True,
        },
        {"in_type": "Bytes[32]", "out_type": "bool", "in_value": b"\xff" * 32, "out_value": True},
        {
            "in_type": "Bytes[32]",
            "out_type": "bool",
            "in_value": b"\x00\x00\x00\x00\x00",
            "out_value": False,
        },
        {
            "in_type": "Bytes[32]",
            "out_type": "bool",
            "in_value": b"\x00\x07\x5B\xCD\x15",
            "out_value": True,
        },
        {
            "in_type": "address",
            "out_type": "bool",
            "in_value": "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            "out_value": True,
        },
    ],
    indirect=True,
)
def test_convert(get_contract_with_gas_estimation, input_values):

    contract_1 = f"""
@external
def test_convert() -> {input_values["out_type"]}:
        return convert({input_values["in_value"]}, {input_values["out_type"]})
        """

    c1 = get_contract_with_gas_estimation(contract_1)
    assert c1.test_convert() == input_values["out_value"]

    contract_2 = f"""
@external
def test_input_convert(x: {input_values["in_type"]}) -> {input_values["out_type"]}:
        return convert(x, {input_values["out_type"]})
        """

    c2 = get_contract_with_gas_estimation(contract_2)
    assert (
        c2.test_input_convert(input_values["contract_call_in_value"]) == input_values["out_value"]
    )

    contract_3 = f"""
bar: {input_values["in_type"]}

@external
def test_state_variable_convert() -> {input_values["out_type"]}:
        self.bar = {input_values["in_value"]}
        return convert(self.bar, {input_values["out_type"]})
        """

    c3 = get_contract_with_gas_estimation(contract_3)
    assert c3.test_state_variable_convert() == input_values["out_value"]


@pytest.mark.parametrize(
    "builtin_constant,out_type,out_value",
    [
        ("ZERO_ADDRESS", "bool", False),
        ("msg.sender", "bool", True),
    ],
)
def test_convert_builtin_constant(
    get_contract_with_gas_estimation, builtin_constant, out_type, out_value
):

    contract = f"""
@external
def convert_builtin_constant() -> {out_type}:
        return convert({builtin_constant}, {out_type})
        """

    c = get_contract_with_gas_estimation(contract)
    assert c.convert_builtin_constant() == out_value


@pytest.mark.parametrize(
    "in_type,out_type,in_value,out_value",
    [
        (
            "bytes32",
            "address",
            (b"\xff" * 20).rjust(32, b"\x00"),
            checksum_encode("0x" + "ff" * 20),
        ),
        ("bytes32", "address", (b"\x01" + b"\xff" * 20).rjust(32, b"\x00"), None),
        ("uint256", "address", 2 ** 160, None),
        ("uint256", "address", 2 ** 160 - 1, checksum_encode("0x" + "ff" * 20)),
    ],
)
def test_convert_clamping(get_contract, assert_tx_failed, in_type, out_type, in_value, out_value):

    contract = f"""
@external
def test_convert(x: {in_type}) -> {out_type}:
    return convert(x, {out_type})
    """

    c = get_contract(contract)
    if not out_value:
        assert_tx_failed(lambda: c.test_convert(in_value))
    else:
        assert c.test_convert(in_value) == out_value


@pytest.mark.parametrize(
    "in_type,out_type,in_value,exception",
    [
        ("bool", "bool", True, InvalidType),
        ("bool", "bool", False, InvalidType),
        ("Bytes[33]", "bool", b"\xff" * 33, TypeMismatch),
        (
            "Bytes[63]",
            "bool",
            b"Hello darkness, my old friend I've come to talk with you again.",
            TypeMismatch,
        ),
    ],
)
def test_invalid_convert(
    get_contract_with_gas_estimation, assert_compile_failed, in_type, out_type, in_value, exception
):

    contract_1 = f"""
@external
def foo():
    bar: {in_type} = {in_value}
    foobar: {out_type} = convert(bar, {out_type})
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(contract_1),
        exception,
    )

    contract_2 = f"""
@external
def foo():
    foobar: {out_type} = convert({in_value}, {out_type})
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(contract_2),
        exception,
    )

    contract_3 = f"""
@external
def foo(bar: {in_type}) -> {out_type}:
        return convert(bar, {out_type})
        """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(contract_3),
        exception,
    )
