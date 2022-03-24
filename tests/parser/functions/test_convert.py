from decimal import Decimal

import pytest

from vyper.codegen.types import (
    BASE_TYPES,
    BYTES_M_TYPES,
    SIGNED_INTEGER_TYPES,
    UNSIGNED_INTEGER_TYPES,
    parse_integer_typeinfo,
)
from vyper.exceptions import InvalidLiteral, InvalidType, OverflowException, TypeMismatch
from vyper.utils import checksum_encode


def hex_to_signed_int(hexstr, bits):
    val = int(hexstr, 16)
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


def _get_type_N(type_):
    """
    Helper function to extract N from typeN (e.g. uint256, bytes32, Bytes[32])
    """
    if "int" in type_:
        return parse_integer_typeinfo(type_).bits
    if type_.startswith("bytes"):
        return int(type_[5:])
    if type_.startswith("Bytes"):
        return int(type_[6:-1])
    return None


def _get_nibble(type_):
    """
    Helper function to extract number of nibbles from a type for hexadecimal string
    """
    type_N = _get_type_N(type_)
    if type_.startswith("bytes"):
        return type_N * 2
    elif type_.startswith("Bytes"):
        return type_N * 2
    elif type_.startswith("int"):
        return type_N // 4
    elif type_.startswith("uint"):
        return type_N // 4
    elif type_ == "decimal":
        return 168 // 4
    return None


def _generate_valid_test_cases_for_type(type_, count=None):
    """
    Helper function to generate the test cases for a specific type.
    """
    if type_ == "address":
        return [
            "0x0000000000000000000000000000000000000000",
            "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
        ]

    elif type_ == "bool":
        return [
            True,
            False,
        ]

    elif type_ == "bytes":
        return [
            "0x" + ("00" * count),
            "0x" + ("00" * (count - 1)) + "01",
            "0x" + ("FF" * count),
        ]

    elif type_ == "Bytes":
        return [
            b"",
            b"\x00",
            b"\x00" * count,
            b"\x01",
            b"\x00\x01",
            b"\xff" * (count - 1) + b"\xfe",
            b"\xff" * count,
        ]

    elif type_ == "decimal":
        return [
            "0.0",
            "0.0000000001",
            "0.9999999999",
            "1.0",
            str(2 ** (count - 1) - 2) + ".9999999999"
            if (count and count < 127)
            else "170141183460469231731687303715884105726.9999999999",  # 2 ** 127 - 1.0000000001
            "-0.0000000001",
            "-0.9999999999",
            "-1.0",
            str(-(2 ** (count - 1) - 1)) + ".9999999999" if (count and count < 127)
            # - (2 ** 127 - 0.0000000001)
            else "-170141183460469231731687303715884105727.9999999999",
        ]

    elif type_ == "int":
        return [
            0,
            1,
            2 ** (count - 1) - 2,
            2 ** (count - 1) - 1,
            -1,
            -(2 ** (count - 1)),
            -(2 ** (count - 1) - 1),
        ]

    elif type_ == "uint":
        return [0, 1, 2 ** count - 2, 2 ** count - 1]


def _generate_input_values_dict(in_type, out_type, cases, out_values):
    """
    Helper function to generate the test values for a specific input type and output type,
    and to modify the output values based on the input type and output type where necessary.
    """
    res = []
    for c, ov in zip(cases, out_values):

        if out_type == "address" and ov == "EVALUATE":

            # Compute the output value where the output type is address
            # and the placeholder value 0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF
            # is used

            # Modify input value by clamping to 160 bits

            n = _get_nibble(in_type)

            if in_type.startswith("bytes"):
                index = 2 if n <= 40 else n - 40 + 2
                ov = checksum_encode("0x" + c[index:].rjust(40, "0"))
                c = "0x" + "0" * (index - 2) + c[index:]

            if in_type.startswith("Bytes"):
                index = 0 if n <= 40 else n - 40
                ov = checksum_encode("0x" + c.hex()[index:].rjust(40, "0"))
                c = b"\x00" * (index // 2) + c[index // 2 :]

            if in_type.startswith("uint"):
                index = 2 if n <= 40 else n - 40 + 2
                ov = checksum_encode("0x" + hex(c)[index:].rjust(40, "0"))
                c = int("0x" + "0" * (index - 2) + hex(c)[index:], 16)

        if out_type.startswith("uint") and ov == "EVALUATE":

            # Modify input value by clamping to number of bits of uint

            if in_type == "address":
                n = _get_nibble(out_type)
                index = 42 - n if n <= 40 else 2
                c = checksum_encode("0x" + "0" * (index - 2) + c[index:])
                ov = int(c, 16)

            if in_type.startswith("bytes"):
                in_n = _get_nibble(in_type)
                out_n = _get_nibble(out_type)

                if in_n > out_n:
                    # Clamp input value
                    index = in_n - out_n + 2
                    c = "0x" + "0" * (index - 2) + c[index:]

                # Compute output value
                ov = int(c, 16)

            if in_type.startswith("Bytes"):
                in_n = _get_nibble(in_type)
                out_n = _get_nibble(out_type)

                if in_n > out_n:
                    # Clamp input value
                    index = in_n - out_n
                    c = b"\x00" * (index // 2) + c[index // 2 :]

                # Compute output value
                ov = int(c.hex(), 16)

            if in_type == "decimal":
                ov = int(Decimal(c))

            if in_type.startswith("int"):
                ov = c

        if out_type.startswith("int") and ov == "EVALUATE":

            if in_type.startswith("bytes"):
                in_bits = _get_type_N(in_type) * 8
                out_bits = _get_type_N(out_type)

                if in_bits >= out_bits:
                    # Clamp input value
                    in_nibbles = _get_nibble(in_type)
                    out_nibbles = _get_nibble(out_type)

                    index = (in_nibbles - out_nibbles) + 2
                    largest_value_hex = hex(2 ** (out_bits - 1) - 1)

                    c = "0x" + "0" * (index - 2) + largest_value_hex[2:]
                    ov = hex_to_signed_int(c, out_bits)
                else:
                    ov = hex_to_signed_int(c, in_bits)

            if in_type.startswith("Bytes"):
                in_N = _get_type_N(in_type)
                in_bits = in_N * 8
                out_bits = _get_type_N(out_type)
                out_bytes = out_bits // 8

                if in_bits >= out_bits:
                    # Clamp input value

                    index = in_N - out_bytes
                    largest_value_bytes = (2 ** (out_bits - 1) - 1).to_bytes(
                        out_bytes, byteorder="big"
                    )

                    c = b"\x00" * (index) + largest_value_bytes
                    ov = hex_to_signed_int(c.hex(), out_bits)
                else:
                    ov = hex_to_signed_int(c.hex(), in_bits)

            if in_type == "decimal":
                ov = int(Decimal(c))

            if in_type.startswith("uint"):
                ov = c

        if out_type == "decimal" and ov == "EVALUATE":
            out_bits = 160

            if in_type.startswith("bytes"):
                in_N = _get_type_N(in_type)
                in_bits = in_N * 8

                if in_bits >= out_bits:
                    # Clamp input value
                    in_nibbles = _get_nibble(in_type)
                    index = in_nibbles - (out_bits // 4) + 2

                    c = "0x" + "0" * (index - 2) + c[index:]

                ov = Decimal(hex_to_signed_int(c, in_bits)) / 10 ** 10

            if in_type.startswith("Bytes"):
                in_N = _get_type_N(in_type)
                in_bits = in_N * 8

                ov = Decimal(hex_to_signed_int(c.hex(), in_bits)) / 10 ** 10

            if "int" in in_type:
                ov = Decimal(c)

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
    if in_type == "address":
        cases = _generate_valid_test_cases_for_type(in_type)

        if out_type == "uint":
            for t in UNSIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, t, cases, out_values)

        else:
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type == "bool":
        cases = _generate_valid_test_cases_for_type(in_type)

        if out_type == "uint":
            for t in UNSIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, t, cases, out_values)
        elif out_type == "int":
            for s in SIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, s, cases, out_values)
        else:
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type[:5] == "bytes":
        for t in BYTES_M_TYPES:
            in_N = _get_type_N(t)
            cases = _generate_valid_test_cases_for_type("bytes", count=in_N)

            # Skip bytes20 because it is treated as address type
            if in_N == 20:
                continue

            if out_type == "uint":
                for u in UNSIGNED_INTEGER_TYPES:
                    result += _generate_input_values_dict(t, u, cases, out_values)

            elif out_type == "int":
                for s in SIGNED_INTEGER_TYPES:
                    result += _generate_input_values_dict(t, s, cases, out_values)

            else:
                result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type[:5] == "Bytes":
        in_N = _get_type_N(in_type)
        cases = _generate_valid_test_cases_for_type("Bytes", count=in_N)

        if out_type == "uint":
            for u in UNSIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, u, cases, out_values)

        elif out_type == "int":
            for s in SIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, s, cases, out_values)

        else:
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type == "decimal":

        if out_type == "uint":
            for t in UNSIGNED_INTEGER_TYPES:
                out_N = _get_type_N(t)
                cases = _generate_valid_test_cases_for_type(in_type, count=out_N)
                updated_cases, updated_out_values = zip(
                    *[x for x in zip(cases, out_values) if (Decimal(x[0]) > 0)]
                )
                result += _generate_input_values_dict(in_type, t, updated_cases, updated_out_values)

        elif out_type == "int":
            for s in SIGNED_INTEGER_TYPES:
                out_N = _get_type_N(s)
                cases = _generate_valid_test_cases_for_type(in_type, count=out_N)
                result += _generate_input_values_dict(in_type, s, cases, out_values)

        else:
            cases = _generate_valid_test_cases_for_type(in_type)
            if out_type == "decimal":
                cases = [c / (10 ** 10) for c in cases]
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type == "int":
        for t in SIGNED_INTEGER_TYPES:
            in_N = _get_type_N(t)
            cases = _generate_valid_test_cases_for_type(in_type, count=in_N)

            if out_type == "uint":
                for u in UNSIGNED_INTEGER_TYPES:
                    out_N = _get_type_N(u)
                    updated_cases, updated_out_values = zip(
                        *[x for x in zip(cases, out_values) if (x[0] > 0 and x[0] <= 2 ** out_N)]
                    )
                    result += _generate_input_values_dict(t, u, updated_cases, updated_out_values)

            else:
                result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type == "uint":
        for t in UNSIGNED_INTEGER_TYPES:
            in_N = _get_type_N(t)
            cases = _generate_valid_test_cases_for_type(in_type, count=in_N)

            if out_type == "int":
                for s in SIGNED_INTEGER_TYPES:
                    out_N = _get_type_N(s)

                    # Update max values based on intN
                    if out_N <= in_N:
                        cases = _generate_valid_test_cases_for_type(in_type, count=out_N - 1)

                    result += _generate_input_values_dict(t, s, cases, out_values)

            else:
                if out_type == "decimal":
                    if in_N >= 128:
                        cases = _generate_valid_test_cases_for_type(in_type, count=127)
                result += _generate_input_values_dict(t, out_type, cases, out_values)

    return sorted(result, key=lambda d: d["in_type"])


@pytest.mark.parametrize(
    "input_values",
    # Convert to bool
    generate_test_convert_values("uint", "bool", [False, True, True, True])
    + generate_test_convert_values("int", "bool", [False, True, True, True, True, True, True])
    + generate_test_convert_values(
        "decimal", "bool", [False, True, True, True, True, True, True, True, True]
    )
    + generate_test_convert_values("address", "bool", [False, True, True])
    + generate_test_convert_values(
        "Bytes[32]", "bool", [False, False, False, True, True, True, True]
    )
    + generate_test_convert_values("bytes", "bool", [False, True, True])
    # Convert to address
    + generate_test_convert_values(
        "uint",
        "address",
        [
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000001",
            "EVALUATE",  # Placeholder value
            "EVALUATE",  # Placeholder value
        ],
    )
    + generate_test_convert_values(
        "bytes",
        "address",
        [
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000001",
            "EVALUATE",  # Placeholder value
        ],
    )
    + generate_test_convert_values(
        "Bytes[32]",
        "address",
        [
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000001",
            "EVALUATE",  # Placeholder value
            "EVALUATE",  # Placeholder value
        ],
    )
    # Convert to uint
    + generate_test_convert_values("address", "uint", [0, "EVALUATE", "EVALUATE"])
    + generate_test_convert_values("bytes", "uint", [0, 1, "EVALUATE"])
    + generate_test_convert_values("bool", "uint", [1, 0])
    + generate_test_convert_values("Bytes[32]", "uint", [0, 0, 0, 1, 1, "EVALUATE", "EVALUATE"])
    + generate_test_convert_values("decimal", "uint", [0, 0, 0, 1, "EVALUATE"])
    # Convert to int
    + generate_test_convert_values("uint", "int", [0, 1, "EVALUATE", "EVALUATE"])
    + generate_test_convert_values("bytes", "int", [0, 1, "EVALUATE"])
    + generate_test_convert_values("Bytes[32]", "int", [0, 0, 0, 1, 1, "EVALUATE", "EVALUATE"])
    + generate_test_convert_values("bool", "int", [1, 0])
    + generate_test_convert_values("decimal", "int", [0, 0, 0, 1, "EVALUATE", 0, 0, -1, "EVALUATE"])
    # Convert to decimal
    + generate_test_convert_values("bool", "decimal", [1.0, 0.0])
    + generate_test_convert_values("bytes", "decimal", ["EVALUATE", "EVALUATE", "EVALUATE"])
    + generate_test_convert_values(
        "Bytes[5]", "decimal", [0.0, 0.0, 0.0, "1e-10", "1e-10", "EVALUATE", "EVALUATE"]
    )
    + generate_test_convert_values(
        "Bytes[16]", "decimal", [0.0, 0.0, 0.0, "1e-10", "1e-10", "EVALUATE", "EVALUATE"]
    )
    + generate_test_convert_values(
        "int", "decimal", [0.0, 1.0, "EVALUATE", "EVALUATE", -1.0, "EVALUATE", "EVALUATE"]
    )
    + generate_test_convert_values("uint", "decimal", [0.0, 1.0, "EVALUATE", "EVALUATE"]),
)
def test_convert_pass(get_contract_with_gas_estimation, input_values):

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

    skip_c1 = False
    if "int" in in_type and "int" in out_type:
        if in_value >= 0:
            skip_c1 = True
    if ("bytes" in in_type or "Bytes" in in_type) and out_type == "decimal":
        skip_c1 = True

    if in_type.startswith("bytes") and _get_type_N(in_type) != 32:
        # Skip bytesN other than bytes32 because they get read as bytes32
        skip_c1 = True

    if not skip_c1:

        c1 = get_contract_with_gas_estimation(contract_1)
        assert c1.test_convert() == out_value

    contract_2 = f"""
@external
def test_input_convert(x: {in_type}) -> {out_type}:
    return convert(x, {out_type})
    """

    c2 = get_contract_with_gas_estimation(contract_2)

    if in_type == "decimal":
        in_value = Decimal(in_value)
    if out_type == "decimal":
        out_value = Decimal(out_value)

    assert c2.test_input_convert(in_value) == out_value

    contract_3 = f"""
bar: {in_type}

@external
def test_state_variable_convert() -> {out_type}:
    self.bar = {in_value}
    return convert(self.bar, {out_type})
    """

    c3 = get_contract_with_gas_estimation(contract_3)

    if out_type == "decimal":
        out_value = Decimal(out_value)

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
        ("uint256", "decimal", 2 ** 127, None),
        ("int256", "decimal", 2 ** 127, None),
        ("int256", "decimal", 2 ** 255 - 1, None),
        ("int256", "decimal", -(2 ** 127) - 1, None),
        ("int256", "decimal", -(2 ** 255), None),
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
            case = _generate_valid_test_cases_for_type("uint", count=bits)[0]

        elif t.startswith("int"):
            bits = int(t[3:])
            case = _generate_valid_test_cases_for_type("int", count=bits)[0]

        elif t.startswith("bytes"):
            bits = int(t[5:])
            case = _generate_valid_test_cases_for_type("bytes", count=bits)[0]

        elif t.startswith("Bytes"):
            bits = int(t[6:-1])
            case = _generate_valid_test_cases_for_type("Bytes", count=bits)[0]

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
        {
            "in_type": "Bytes[33]",
            "out_type": "uint256",
            "in_value": b"\xff" * 33,
            "exception": TypeMismatch,
        },
        {
            "in_type": "Bytes[63]",
            "out_type": "uint256",
            "in_value": b"Hello darkness, my old friend I've come to talk with you again.",
            "exception": TypeMismatch,
        },
        {
            "in_type": "int256",
            "out_type": "uint256",
            "in_value": -1,
            "exception": InvalidLiteral,
        },
        {
            "in_type": "int256",
            "out_type": "uint256",
            "in_value": -(2 ** 255),
            "exception": InvalidLiteral,
        },
        {
            "in_type": "decimal",
            "out_type": "uint256",
            "in_value": "-27.2319",
            "exception": InvalidLiteral,
        },
        {
            "in_type": "Bytes[33]",
            "out_type": "int256",
            "in_value": b"\xff" * 33,
            "exception": TypeMismatch,
        },
        {
            "in_type": "Bytes[63]",
            "out_type": "int256",
            "in_value": b"Hello darkness, my old friend I've come to talk with you again.",
            "exception": TypeMismatch,
        },
        {
            "in_type": "uint256",
            "out_type": "int256",
            "in_value": 2 ** 256 - 1,
            "exception": InvalidLiteral,
        },
        {
            "in_type": "uint256",
            "out_type": "int256",
            "in_value": 2 ** 255,
            "exception": InvalidLiteral,
        },
        {
            "in_type": "decimal",
            "out_type": "int256",
            "in_value": "180141183460469231731687303715884105728.0",
            "exception": OverflowException,
        },
        {
            "in_type": "uint256",
            "out_type": "decimal",
            "in_value": 2 ** 127,
            "exception": InvalidLiteral,
        },
        {
            "in_type": "address",
            "out_type": "decimal",
            "in_value": "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            "exception": TypeMismatch,
        },
        {
            "in_type": "bytes32",
            "out_type": "decimal",
            "in_value": "0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
            "exception": InvalidLiteral,
        },
        {
            "in_type": "Bytes[33]",
            "out_type": "decimal",
            "in_value": b"\xff" * 33,
            "exception": TypeMismatch,
        },
        {
            "in_type": "Bytes[63]",
            "out_type": "decimal",
            "in_value": b"Hello darkness, my old friend I've come to talk with you again.",
            "exception": TypeMismatch,
        },
    ],
)
def test_invalid_convert(
    get_contract_with_gas_estimation, assert_compile_failed, assert_tx_failed, input_values
):

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

    if exception == InvalidLiteral:
        c1 = get_contract_with_gas_estimation(contract_1)
        assert_tx_failed(lambda: c1.foo())

    else:
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

    if exception in [InvalidLiteral, OverflowException]:
        c3 = get_contract_with_gas_estimation(contract_3)
        if in_type == "decimal":
            in_value = Decimal(in_value)
        assert_tx_failed(lambda: c3.foo(in_value))

    else:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract_3),
            exception,
        )

    contract_4 = f"""
@external
def foo() -> {out_type}:
    return convert({in_value}, {out_type})
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(contract_4),
        exception,
    )
