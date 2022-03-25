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
from vyper.utils import DECIMAL_DIVISOR, MAX_DECIMAL_PLACES, SizeLimits, checksum_encode

# To update when Decimal bound is updated to 2 ** 168 / 10 ** 10
DECIMAL_BITS = 160
ADDRESS_BITS = 160
TEST_TYPES = BASE_TYPES.union({"Bytes[32]"})

MIN_DECIMAL_STR = (
    str(SizeLimits.MINDECIMAL)[:-MAX_DECIMAL_PLACES]
    + "."
    + str(SizeLimits.MINDECIMAL)[-MAX_DECIMAL_PLACES:]
)

MAX_DECIMAL_STR = (
    str(SizeLimits.MAXDECIMAL)[:-MAX_DECIMAL_PLACES]
    + "."
    + str(SizeLimits.MAXDECIMAL)[-MAX_DECIMAL_PLACES:]
)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ONE_ADDRESS = "0x0000000000000000000000000000000000000001"


def hex_to_signed_int(hexstr, bits):
    val = int(hexstr, 16)
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


def signed_int_to_hex(val, bits):
    return hex((val + (1 << bits)) % (1 << bits))


def _get_type_N(type_):
    """
    Helper function to extract N from typeN (e.g. uint256, bytes32, Bytes[32])
    """
    if type_.startswith(("int", "uint")):
        return parse_integer_typeinfo(type_).bits
    if type_.startswith("bytes"):
        return int(type_[5:])
    if type_.startswith("Bytes"):
        return int(type_[6:-1])
    return None


def _get_bits(type_):
    """
    Helper function to get the number of bits from type
    """
    if type_.startswith(("int", "uint")):
        return _get_type_N(type_)
    if type_.startswith(("bytes", "Bytes")):
        return _get_type_N(type_) * 8
    if type == "decimal":
        return DECIMAL_BITS
    return None


def _get_nibble(type_):
    """
    Helper function to extract number of nibbles from a type for hexadecimal string
    """
    type_N = _get_type_N(type_)
    if type_.startswith(("bytes", "Bytes")):
        return type_N * 2
    elif type_.startswith(("int", "uint")):
        return type_N // 4
    elif type_ == "decimal":
        return DECIMAL_BITS // 4
    elif type_ == "address":
        return ADDRESS_BITS // 4
    return None


def _get_case_type(type_):
    """
    Helper function to get the case type for `_generate_valid_test_cases_for_type`
    """
    if type_.startswith("uint"):
        return "uint"

    elif type_.startswith("int"):
        return "int"

    elif type_.startswith("bytes"):
        return "bytes"

    elif type_.startswith("Bytes"):
        return "Bytes"
    return type_


def _get_all_types_for_case_type(case_type):
    """
    Helper function to all types for a given case type
    """
    if case_type == "int":
        return SIGNED_INTEGER_TYPES
    elif case_type == "uint":
        return UNSIGNED_INTEGER_TYPES
    elif case_type == "bytes":
        return BYTES_M_TYPES
    return case_type


def _generate_valid_test_cases_for_type(type_, count=None):
    """
    Helper function to generate the test cases for a specific type.
    """
    if type_ == "address":
        return [
            ZERO_ADDRESS,
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
            str(2 ** (count - 1) - 1) + ".0000000000"
            if (count and count < 127)
            else MAX_DECIMAL_STR,
            "-0.0000000001",
            "-0.9999999999",
            "-1.0",
            str(-(2 ** (count - 1))) + ".0000000000"
            if (count and count < 127)
            else MIN_DECIMAL_STR,
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

    To defer the evaluation of the output value to this function, use "EVALUATE" as a
    placeholder when defining the `out_values` in pytest.mark.parametrize.
    """
    res = []
    for c, ov in zip(cases, out_values):

        if out_type == "address" and ov == "EVALUATE":

            # Modify input value by clamping to 160 bits
            n = _get_nibble(in_type)
            out_nibbles = _get_nibble(out_type)

            if in_type.startswith("bytes"):
                index = 2 if n <= out_nibbles else n - out_nibbles + 2
                ov = checksum_encode("0x" + c[index:].rjust(out_nibbles, "0"))
                c = "0x" + "0" * (index - 2) + c[index:]

            elif in_type.startswith("Bytes"):
                index = 0 if n <= out_nibbles else n - out_nibbles
                ov = checksum_encode("0x" + c.hex()[index:].rjust(out_nibbles, "0"))
                c = b"\x00" * (index // 2) + c[index // 2 :]

            elif in_type.startswith("uint"):
                index = 2 if n <= out_nibbles else n - out_nibbles + 2
                ov = checksum_encode("0x" + hex(c)[index:].rjust(out_nibbles, "0"))
                c = int("0x" + "0" * (index - 2) + hex(c)[index:], 16)

        elif out_type.startswith("uint") and ov == "EVALUATE":

            # Modify input value by clamping to number of bits of uint

            if in_type == "address":
                in_nibbles = _get_nibble(in_type)
                out_nibbles = _get_nibble(out_type)
                index = in_nibbles + 2 - out_nibbles if out_nibbles <= in_nibbles else 2
                c = checksum_encode("0x" + "0" * (index - 2) + c[index:])
                ov = int(c, 16)

            elif in_type.startswith("bytes"):
                in_nibbles = _get_nibble(in_type)
                out_nibbles = _get_nibble(out_type)

                if in_nibbles > out_nibbles:
                    # Clamp input value
                    index = in_nibbles - out_nibbles + 2
                    c = "0x" + "0" * (index - 2) + c[index:]

                # Compute output value
                ov = int(c, 16)

            elif in_type.startswith("Bytes"):
                in_nibbles = _get_nibble(in_type)
                out_nibbles = _get_nibble(out_type)

                if in_nibbles > out_nibbles:
                    # Clamp input value
                    index = in_nibbles - out_nibbles
                    c = b"\x00" * (index // 2) + c[index // 2 :]

                # Compute output value
                ov = int(c.hex(), 16)

            elif in_type == "decimal":
                ov = int(Decimal(c))

            elif in_type.startswith("int"):
                ov = c

        elif out_type.startswith("int") and ov == "EVALUATE":

            if in_type.startswith("bytes"):
                in_bits = _get_bits(in_type)
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

            elif in_type.startswith("Bytes"):
                in_N = _get_type_N(in_type)
                in_bits = _get_bits(in_type)
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

            elif in_type == "decimal":
                ov = int(Decimal(c))

            elif in_type.startswith("uint"):
                ov = c

        elif out_type == "decimal" and ov == "EVALUATE":
            #################################################################################
            # NOTE: Vyper uses a decimal divisor of 10000000000 (or 10^10).
            #
            #       This means that `decimal` type variables can store values
            #       that are of 1/10000000000.
            #
            #       Because of this, when converting from `decimal` to `bytes32`,
            #       the conversion can be thought of as converting integer result of
            #       the decimal value of interest multiplied by 10000000000.
            #
            #       For example, converting the decimal value `5.0` to `byte32`
            #       can be thought of as giving the `bytes32` value of the integer
            #       result of 5 * 10000000000 = 50000000000
            #################################################################################
            out_bits = DECIMAL_BITS

            if in_type.startswith("bytes"):
                in_bits = _get_bits(in_type)

                if in_bits >= out_bits:
                    # Clamp input value
                    in_nibbles = _get_nibble(in_type)
                    index = in_nibbles - (out_bits // 4) + 2

                    c = "0x" + "0" * (index - 2) + c[index:]

                ov = Decimal(hex_to_signed_int(c, in_bits)) / DECIMAL_DIVISOR

            elif in_type.startswith("Bytes"):
                in_bits = _get_bits(in_type)

                ov = Decimal(hex_to_signed_int(c.hex(), in_bits)) / DECIMAL_DIVISOR

            elif in_type.startswith(("int", "uint")):
                ov = Decimal(c)

        elif out_type.startswith("bytes") and ov == "EVALUATE":
            out_nibbles = _get_nibble(out_type)

            if in_type == "address":
                ov = bytes.fromhex(c[2:].rjust(out_nibbles, "0"))

            elif in_type == "bool":
                ov = bytes.fromhex(hex(int(c))[2].rjust(out_nibbles, "0"))

            elif in_type.startswith("Bytes"):
                ov = bytes.fromhex(c.hex().ljust(out_nibbles, "0"))

            elif in_type == "decimal":
                in_hex_str = signed_int_to_hex(int(Decimal(c) * DECIMAL_DIVISOR), 256)[2:].rjust(
                    64, "0"
                )
                if out_nibbles < 64:
                    index = 64 - (out_nibbles)
                    in_hex_str = in_hex_str[index:]
                ov = bytes.fromhex(in_hex_str)

            elif in_type.startswith("uint"):
                ov = bytes.fromhex(hex(c)[2:].rjust(out_nibbles, "0"))

            elif in_type.startswith("int"):
                in_N = _get_type_N(in_type)
                msb = "f" if c < 0 else "0"
                ov = bytes.fromhex(signed_int_to_hex(c, in_N)[2:].rjust(out_nibbles, msb))

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

        if out_type == "bytes":
            for b in BYTES_M_TYPES:
                out_N = _get_type_N(b)
                out_bits = _get_bits(b)
                if out_bits < ADDRESS_BITS or out_N == ADDRESS_BITS // 8:
                    continue
                result += _generate_input_values_dict(in_type, b, cases, out_values)

        elif out_type == "uint":
            for t in UNSIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, t, cases, out_values)

        else:
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type == "bool":
        cases = _generate_valid_test_cases_for_type(in_type)

        if out_type == "bytes":
            for b in BYTES_M_TYPES:
                result += _generate_input_values_dict(in_type, b, cases, out_values)

        elif out_type == "int":
            for s in SIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, s, cases, out_values)

        elif out_type == "uint":
            for t in UNSIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, t, cases, out_values)

        else:
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type[:5] == "bytes":
        for t in BYTES_M_TYPES:
            in_N = _get_type_N(t)
            cases = _generate_valid_test_cases_for_type("bytes", count=in_N)

            # Skip bytes20 because it is treated as address type
            if in_N == ADDRESS_BITS // 8:
                continue

            if out_type == "int":
                for s in SIGNED_INTEGER_TYPES:
                    result += _generate_input_values_dict(t, s, cases, out_values)

            elif out_type == "uint":
                for u in UNSIGNED_INTEGER_TYPES:
                    result += _generate_input_values_dict(t, u, cases, out_values)

            else:
                result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type[:5] == "Bytes":
        in_N = _get_type_N(in_type)
        cases = _generate_valid_test_cases_for_type("Bytes", count=in_N)

        if out_type == "bytes":
            for b in BYTES_M_TYPES:
                out_N = _get_type_N(b)
                if out_N < in_N:
                    continue
                result += _generate_input_values_dict(in_type, b, cases, out_values)

        elif out_type == "int":
            for s in SIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, s, cases, out_values)

        elif out_type == "uint":
            for u in UNSIGNED_INTEGER_TYPES:
                result += _generate_input_values_dict(in_type, u, cases, out_values)

        else:
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type == "decimal":
        cases = _generate_valid_test_cases_for_type(in_type, count=128)
        if out_type == "bytes":
            for b in BYTES_M_TYPES:
                result += _generate_input_values_dict(in_type, b, cases, out_values)

        elif out_type == "int":
            for s in SIGNED_INTEGER_TYPES:
                out_N = _get_type_N(s)
                cases = _generate_valid_test_cases_for_type(in_type, count=out_N)
                result += _generate_input_values_dict(in_type, s, cases, out_values)

        elif out_type == "uint":
            for t in UNSIGNED_INTEGER_TYPES:
                out_N = _get_type_N(t)
                cases = _generate_valid_test_cases_for_type(in_type, count=out_N)
                updated_cases, updated_out_values = zip(
                    *[x for x in zip(cases, out_values) if (Decimal(x[0]) > 0)]
                )
                result += _generate_input_values_dict(in_type, t, updated_cases, updated_out_values)

        else:
            cases = _generate_valid_test_cases_for_type(in_type)
            result += _generate_input_values_dict(in_type, out_type, cases, out_values)

    elif in_type == "int":
        for t in SIGNED_INTEGER_TYPES:
            in_N = _get_type_N(t)
            cases = _generate_valid_test_cases_for_type(in_type, count=in_N)

            if out_type == "bytes":
                for b in BYTES_M_TYPES:
                    out_bits = _get_bits(b)
                    if out_bits < in_N:
                        continue
                    result += _generate_input_values_dict(t, b, cases, out_values)

            elif out_type == "uint":
                for u in UNSIGNED_INTEGER_TYPES:
                    out_N = _get_type_N(u)
                    updated_cases, updated_out_values = zip(
                        *[x for x in zip(cases, out_values) if (x[0] > 0 and x[0] <= 2 ** out_N)]
                    )
                    result += _generate_input_values_dict(t, u, updated_cases, updated_out_values)

            else:
                if out_type == "decimal":
                    if in_N > 128:
                        cases = _generate_valid_test_cases_for_type(in_type, count=128)
                result += _generate_input_values_dict(t, out_type, cases, out_values)

    elif in_type == "uint":
        for t in UNSIGNED_INTEGER_TYPES:
            in_N = _get_type_N(t)
            cases = _generate_valid_test_cases_for_type(in_type, count=in_N)

            if out_type == "bytes":
                for b in BYTES_M_TYPES:
                    out_bits = _get_bits(b)
                    if out_bits < in_N:
                        continue
                    result += _generate_input_values_dict(t, b, cases, out_values)

            elif out_type == "int":
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
    generate_test_convert_values("address", "bool", [False, True, True])
    + generate_test_convert_values("bytes", "bool", [False, True, True])
    + generate_test_convert_values(
        "Bytes[32]", "bool", [False, False, False, True, True, True, True]
    )
    + generate_test_convert_values(
        "decimal", "bool", [False, True, True, True, True, True, True, True, True]
    )
    + generate_test_convert_values("int", "bool", [False, True, True, True, True, True, True])
    + generate_test_convert_values("uint", "bool", [False, True, True, True])
    # Convert to address
    + generate_test_convert_values("bytes", "address", [ZERO_ADDRESS, ONE_ADDRESS, "EVALUATE"])
    + generate_test_convert_values(
        "Bytes[32]",
        "address",
        [
            ZERO_ADDRESS,
            ZERO_ADDRESS,
            ZERO_ADDRESS,
            ONE_ADDRESS,
            ONE_ADDRESS,
            "EVALUATE",
            "EVALUATE",
        ],
    )
    + generate_test_convert_values(
        "uint", "address", [ZERO_ADDRESS, ONE_ADDRESS, "EVALUATE", "EVALUATE"]
    )
    # Convert to uint
    + generate_test_convert_values("address", "uint", [0, "EVALUATE", "EVALUATE"])
    + generate_test_convert_values("bytes", "uint", [0, 1, "EVALUATE"])
    + generate_test_convert_values("bool", "uint", [1, 0])
    + generate_test_convert_values("Bytes[32]", "uint", [0, 0, 0, 1, 1, "EVALUATE", "EVALUATE"])
    + generate_test_convert_values("decimal", "uint", [0, 0, 0, 1, "EVALUATE"])
    + generate_test_convert_values("int", "uint", [0, 1, "EVALUATE", "EVALUATE", None, None])
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
    + generate_test_convert_values("uint", "decimal", [0.0, 1.0, "EVALUATE", "EVALUATE"])
    # Convert to bytes
    + generate_test_convert_values(
        "uint", "bytes", ["EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE"]
    )
    + generate_test_convert_values(
        "int",
        "bytes",
        ["EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE"],
    )
    + generate_test_convert_values("address", "bytes", ["EVALUATE", "EVALUATE", "EVALUATE"])
    + generate_test_convert_values(
        "Bytes[32]",
        "bytes",
        ["EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE"],
    )
    + generate_test_convert_values(
        "Bytes[15]",
        "bytes",
        ["EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE", "EVALUATE"],
    )
    + generate_test_convert_values("bool", "bytes", ["EVALUATE", "EVALUATE"])
    + generate_test_convert_values(
        "decimal",
        "bytes",
        [
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
            "EVALUATE",
        ],
    ),
)
def test_convert_pass(get_contract_with_gas_estimation, input_values):

    if input_values["out_type"] == "address" and input_values["out_value"] == ZERO_ADDRESS:
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
    if in_type.startswith(("int", "uint")) and out_type.startswith(("int", "uint")):
        # Skip conversion of positive integer literals because compiler reads them
        # as target type.
        if in_value >= 0:
            skip_c1 = True

    if in_type.startswith(("bytes", "Bytes")) and out_type == "decimal":
        skip_c1 = True

    if in_type.startswith(("int", "uint")) and out_type.startswith("bytes"):
        # Skip conversion of integer literals because they are of uint256 / int256
        # types, unless it is bytes32
        if out_type != "bytes32":
            skip_c1 = True

    if in_type.startswith("Bytes") and out_type.startswith("bytes"):
        if _get_type_N(in_type) == _get_type_N(out_type):
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

    contract_4 = f"""

@external
def test_state_variable_convert() -> {out_type}:
    bar: {in_type} = {in_value}
    return convert(bar, {out_type})
    """

    c4 = get_contract_with_gas_estimation(contract_4)

    if out_type == "decimal":
        out_value = Decimal(out_value)

    assert c4.test_state_variable_convert() == out_value


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


def generate_test_cases_for_same_type_conversion():
    """
    Helper function to generate test cases for invalid conversion of same types.
    """
    res = []
    for t in TEST_TYPES:
        in_N = _get_type_N(t)
        case_type = _get_case_type(t)

        case = _generate_valid_test_cases_for_type(case_type, count=in_N)[0]
        res.append({"in_type": t, "out_type": t, "in_value": case, "exception": InvalidType})

    return res


def generate_test_cases_for_byte_array_type_mismatch():
    res = []
    for t in BASE_TYPES:

        res.append(
            {
                "in_type": "Bytes[33]",
                "out_type": t,
                "in_value": b"\xff" * 33,
                "exception": TypeMismatch,
            }
        )

        res.append(
            {
                "in_type": "Bytes[63]",
                "out_type": t,
                "in_value": b"Hello darkness, my old friend I've come to talk with you again.",
                "exception": TypeMismatch,
            }
        )

    return res


def generate_test_cases_for_invalid_numeric_conversion():
    res = []
    # Outer loop = out_type
    # Inner loop = in_type

    # Convert to uint
    for u in UNSIGNED_INTEGER_TYPES:
        for s in SIGNED_INTEGER_TYPES:
            out_N = _get_type_N(s)
            cases = [-1, -(2 ** (out_N - 1))]
            for c in cases:
                res.append(
                    {
                        "in_type": s,
                        "out_type": u,
                        "in_value": c,
                        "exception": InvalidLiteral,
                    }
                )

        # Decimal
        decimal_cases = ["-1.0", MIN_DECIMAL_STR]

        for d in decimal_cases:
            res.append(
                {
                    "in_type": "decimal",
                    "out_type": u,
                    "in_value": d,
                    "exception": InvalidLiteral,
                }
            )

    # Convert to int
    for s in SIGNED_INTEGER_TYPES:
        out_N = _get_type_N(s)

        for u in UNSIGNED_INTEGER_TYPES:
            in_N = _get_type_N(u)
            if in_N < out_N:
                # Skip if max uint value is within bounds of int
                continue
            cases = [2 ** in_N - 1, 2 ** (in_N - 1)]
            for c in cases:
                res.append(
                    {
                        "in_type": u,
                        "out_type": s,
                        "in_value": c,
                        "exception": InvalidLiteral,
                    }
                )

        # Decimal
        decimal_cases = [MIN_DECIMAL_STR, MAX_DECIMAL_STR]

        if out_N < 128:
            for d in decimal_cases:
                res.append(
                    {
                        "in_type": "decimal",
                        "out_type": s,
                        "in_value": d,
                        "exception": InvalidLiteral,
                    }
                )

    # Convert to decimal
    for u in UNSIGNED_INTEGER_TYPES:
        in_N = _get_type_N(u)
        if in_N >= 128:
            cases = [2 ** in_N - 1, 2 ** (in_N - 1)]
            for c in cases:
                res.append(
                    {
                        "in_type": u,
                        "out_type": "decimal",
                        "in_value": c,
                        "exception": InvalidLiteral,
                    }
                )

    for s in SIGNED_INTEGER_TYPES:
        in_N = _get_type_N(s)
        if in_N > 128:
            cases = [2 ** (in_N - 1) - 1, -(2 ** (in_N - 1))]
            for c in cases:
                res.append(
                    {
                        "in_type": s,
                        "out_type": "decimal",
                        "in_value": c,
                        "exception": InvalidLiteral,
                    }
                )

    return res


def generate_test_cases_for_invalid_to_address_conversion():
    res = []

    for u in UNSIGNED_INTEGER_TYPES:
        in_N = _get_type_N(u)
        if in_N > 160:
            cases = [2 ** 160, 2 ** in_N - 1, 2 ** (in_N - 1)]
            for c in cases:
                res.append(
                    {
                        "in_type": u,
                        "out_type": "address",
                        "in_value": c,
                        "exception": "CLAMP",
                    }
                )

    for b in BYTES_M_TYPES:
        in_nibbles = _get_nibble(b)
        out_nibbles = _get_nibble("address")
        if in_nibbles > out_nibbles:
            cases = [
                "0x" + hex(2 ** 160)[2:].rjust(in_nibbles, "0"),
                "0x" + "f" * in_nibbles,
                "0x" + "f" * (in_nibbles - 1) + "e",
            ]
            for c in cases:
                res.append(
                    {
                        "in_type": b,
                        "out_type": "address",
                        "in_value": c,
                        "exception": "CLAMP",
                    }
                )

    return res


def generate_test_cases_for_decimal_overflow():
    res = []

    for t in TEST_TYPES.difference({"Bytes[32]", "address", "decimal"}):
        res.append(
            {
                "in_type": "decimal",
                "out_type": t,
                "in_value": "180141183460469231731687303715884105728.0",
                "exception": OverflowException,
            }
        )

    return res


INVALID_CONVERSIONS = [
    # (in_type, out_type, case type for out_type)
    ("address", "decimal"),
    ("address", "int"),
    ("bool", "address"),
    ("int", "address"),
    ("decimal", "address"),
]


def generate_test_cases_for_dislike_type_mismatch():

    res = []

    for invalid_pair in INVALID_CONVERSIONS:

        in_type = invalid_pair[0]
        out_type = invalid_pair[1]

        if in_type in TEST_TYPES and out_type in TEST_TYPES:
            in_N = _get_type_N(in_type)
            case = _generate_valid_test_cases_for_type(in_type, count=in_N)[-1]

            res.append(
                {
                    "in_type": in_type,
                    "out_type": out_type,
                    "in_value": case,
                    "exception": TypeMismatch,
                }
            )

        elif in_type not in TEST_TYPES:
            in_types = _get_all_types_for_case_type(in_type)

            for i in in_types:
                in_N = _get_type_N(i)
                case = _generate_valid_test_cases_for_type(in_type, count=in_N)[-1]

                res.append(
                    {
                        "in_type": i,
                        "out_type": out_type,
                        "in_value": case,
                        "exception": TypeMismatch,
                    }
                )

        elif out_type not in TEST_TYPES:

            out_types = _get_all_types_for_case_type(out_type)
            in_N = _get_type_N(in_type)
            case = _generate_valid_test_cases_for_type(in_type, count=in_N)[-1]

            for o in out_types:

                res.append(
                    {
                        "in_type": in_type,
                        "out_type": o,
                        "in_value": case,
                        "exception": TypeMismatch,
                    }
                )

    return res


@pytest.mark.parametrize(
    "input_values",
    generate_test_cases_for_same_type_conversion()
    + generate_test_cases_for_byte_array_type_mismatch()
    + generate_test_cases_for_invalid_numeric_conversion()
    + generate_test_cases_for_invalid_to_address_conversion()
    + generate_test_cases_for_dislike_type_mismatch()
    + [
        {
            "in_type": "bytes32",
            "out_type": "decimal",
            "in_value": "0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
            "exception": InvalidLiteral,
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

    if exception in (InvalidLiteral, "CLAMP"):
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

    skip_c2 = False
    if in_type == "address":
        skip_c2 = True

    if not skip_c2:
        if exception in ("CLAMP",):
            c2 = get_contract_with_gas_estimation(contract_2)
            assert_tx_failed(lambda: c2.foo())

        else:
            assert_compile_failed(
                lambda: get_contract_with_gas_estimation(contract_2),
                exception,
            )

    # Test contract for clamping
    # Test cases for clamping failures produce an InvalidLiteral exception in contracts 2 and 4
    contract_3 = f"""
@external
def foo(bar: {in_type}) -> {out_type}:
    return convert(bar, {out_type})
    """

    if exception in (InvalidLiteral, OverflowException, "CLAMP"):
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

    skip_c4 = False
    if in_type == "address":
        skip_c4 = True

    if not skip_c4:
        if exception in ("CLAMP",):
            c4 = get_contract_with_gas_estimation(contract_4)
            assert_tx_failed(lambda: c4.foo())

        else:
            assert_compile_failed(
                lambda: get_contract_with_gas_estimation(contract_4),
                exception,
            )
