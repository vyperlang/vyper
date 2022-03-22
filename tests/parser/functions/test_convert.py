from decimal import Decimal

import pytest

from vyper.codegen.types import (
    BASE_TYPES,
    BYTES_M_TYPES,
    SIGNED_INTEGER_TYPES,
    UNSIGNED_INTEGER_TYPES,
)
from vyper.exceptions import InvalidType, TypeMismatch
from vyper.utils import checksum_encode


def _generate_valid_test_cases_for_type(type_, bits=None):
    """
    Helper function to generate the test cases for a specific type.
    """
    if type_ == "uint":
        return [0, 1, 2 ** bits - 2, 2 ** bits - 1]
    elif type_ == "int":
        return [
            0,
            1,
            2 ** (bits - 1) - 2,
            2 ** (bits - 1) - 1,
            -(2 ** (bits - 1)),
            -(2 ** (bits - 1) - 1),
        ]
    elif type_ == "decimal":
        return [
            "0.0",
            "0.0000000001",
            "0.9999999999",
            "1.0",
            "170141183460469231731687303715884105726.9999999999",  # 2 ** 127 - 1.0000000001
            "-0.0000000001",
            "-0.9999999999",
            "-1.0",
            "-170141183460469231731687303715884105727.9999999999",  # - (2 ** 127 - 0.0000000001)
        ]
    elif type_ == "address":
        return [
            "0x0000000000000000000000000000000000000000",
            "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
        ]
    elif type_ == "Bytes":
        return [
            b"",
            b"\x00",
            b"\x00" * bits,
            b"\x01",
            b"\x00\x01",
            b"\xff" * (bits - 1) + b"\xfe",
            b"\xff" * bits,
        ]
    elif type_ == "bytes":
        return [
            "0x" + ("00" * bits),
            "0x" + ("00" * (bits - 1)) + "01",
            checksum_encode("0x" + ("FF" * bits)) if bits == 20 else "0x" + ("FF" * bits),
        ]
    elif type_ == "bool":
        return [
            True,
            False,
        ]


def _generate_input_values_dict(in_type, out_type, cases, out_values):
    """
    Helper function to generate the test values for a specific input type and output type,
    and to modify the output values based on the input type and output type where necessary.
    """
    res = []
    for c, ov in zip(cases, out_values):

        if out_type == "address" and ov == "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF":

            # Compute the output value where the output type is address
            # and the placeholder value 0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF
            # is used

            if in_type.startswith("bytes"):
                ov = checksum_encode("0x" + c[2:].rjust(40, "0"))

            if in_type.startswith("Bytes"):
                ov = checksum_encode("0x" + c.hex().rjust(40, "0"))

            if in_type.startswith("uint"):
                ov = checksum_encode("0x" + hex(c)[2:].rjust(40, "0"))

        res.append(
            {
                "in_type": in_type,
                "out_type": out_type,
                "in_value": c,
                "out_value": ov,
            }
        )
    return res


def generate_test_convert_values(in_type, out_type, out_values):
    """
    Helper function to generate the test values for a generic input type.
    """
    result = []
    if in_type == "uint":

        unsigned_integer_types = (
            [u for u in UNSIGNED_INTEGER_TYPES if int(u[4:]) < 160]
            if out_type == "address"
            else UNSIGNED_INTEGER_TYPES
        )
        for t in unsigned_integer_types:
            bits = int(t[4:])
            cases = _generate_valid_test_cases_for_type(in_type, bits)
            result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type == "int":
        for t in SIGNED_INTEGER_TYPES:
            bits = int(t[3:])
            cases = _generate_valid_test_cases_for_type(in_type, bits)
            result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type[:5] == "bytes":
        bytes_types = (
            [b for b in BYTES_M_TYPES if int(b[5:]) < 20]
            if out_type == "address"
            else BYTES_M_TYPES
        )
        for t in bytes_types:
            bits = int(t[5:])
            cases = _generate_valid_test_cases_for_type("bytes", bits)
            result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type[:5] == "Bytes":
        bits = int(in_type[6:-1])
        print(bits)
        cases = _generate_valid_test_cases_for_type("Bytes", bits)
        result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type in ["decimal", "address"]:
        cases = _generate_valid_test_cases_for_type(in_type)
        result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    return sorted(result, key=lambda d: d["in_type"])


@pytest.mark.parametrize(
    "input_values",
    generate_test_convert_values("uint", "bool", [False, True, True, True])
    + generate_test_convert_values("int", "bool", [False, True, True, True, True, True])
    + generate_test_convert_values(
        "decimal", "bool", [False, True, True, True, True, True, True, True, True]
    )
    + generate_test_convert_values("address", "bool", [False, True, True])
    + generate_test_convert_values(
        "Bytes[32]", "bool", [False, False, False, True, True, True, True]
    )
    + generate_test_convert_values("bytes", "bool", [False, True, True])
    + generate_test_convert_values(
        "uint",
        "address",
        [
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000001",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",  # Placeholder value
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",  # Placeholder value
        ],
    )
    + generate_test_convert_values(
        "bytes",
        "address",
        [
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000001",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",  # Placeholder value
        ],
    )
    + generate_test_convert_values(
        "Bytes[19]",
        "address",
        [
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000001",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",  # Placeholder value
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",  # Placeholder value
        ],
    ),
)
def test_convert(get_contract_with_gas_estimation, input_values):

    if (
        input_values["out_type"] == "address"
        and input_values["out_value"] == "0x0000000000000000000000000000000000000000"
    ):
        input_values["out_value"] = None

    in_type = input_values["in_type"]
    out_type = input_values["out_type"]
    in_value = input_values["in_value"]
    out_value = input_values["out_value"]

    contract_1 = f"""
@external
def test_convert() -> {out_type}:
    return convert({in_value}, {out_type})
    """

    c1 = get_contract_with_gas_estimation(contract_1)
    assert c1.test_convert() == out_value

    contract_2 = f"""
@external
def test_input_convert(x: {in_type}) -> {out_type}:
    return convert(x, {out_type})
    """

    c2 = get_contract_with_gas_estimation(contract_2)
    if in_type == "decimal":
        assert c2.test_input_convert(Decimal(in_value)) == out_value
    else:
        assert c2.test_input_convert(in_value) == out_value

    contract_3 = f"""
bar: {in_type}

@external
def test_state_variable_convert() -> {out_type}:
    self.bar = {in_value}
    return convert(self.bar, {out_type})
    """

    c3 = get_contract_with_gas_estimation(contract_3)
    assert c3.test_state_variable_convert() == out_value


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


def generate_test_cases_for_same_type_conversion():
    """
    Helper function to generate test cases for invalid conversion of same types.
    """
    res = []
    for t in BASE_TYPES.union({"Bytes[32]"}):
        if t.startswith("uint"):
            bits = int(t[4:])
            case = _generate_valid_test_cases_for_type("uint", bits)[0]

        elif t.startswith("int"):
            bits = int(t[3:])
            case = _generate_valid_test_cases_for_type("int", bits)[0]

        elif t.startswith("bytes"):
            bits = int(t[5:])
            case = _generate_valid_test_cases_for_type("bytes", bits)[0]

        elif t.startswith("Bytes"):
            bits = int(t[6:-1])
            case = _generate_valid_test_cases_for_type("Bytes", bits)[0]

        else:
            case = _generate_valid_test_cases_for_type(t)[0]

        res.append({"in_type": t, "out_type": t, "in_value": case, "exception": InvalidType})

    return res


@pytest.mark.parametrize(
    "input_values",
    generate_test_cases_for_same_type_conversion()
    + [
        {
            "in_type": "Bytes[33]",
            "out_type": "bool",
            "in_value": b"\xff" * 33,
            "exception": TypeMismatch,
        },
        {
            "in_type": "Bytes[63]",
            "out_type": "bool",
            "in_value": b"Hello darkness, my old friend I've come to talk with you again.",
            "exception": TypeMismatch,
        },
    ],
)
def test_invalid_convert(get_contract_with_gas_estimation, assert_compile_failed, input_values):

    in_type = input_values["in_type"]
    out_type = input_values["out_type"]
    in_value = input_values["in_value"]
    exception = input_values["exception"]

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
