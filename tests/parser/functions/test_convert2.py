import math
from decimal import Decimal
from itertools import permutations

import pytest
from eth_abi import decode_single, encode_single
from eth_utils import add_0x_prefix, clamp, remove_0x_prefix

from vyper.codegen.types import (
    BASE_TYPES,
    BYTES_M_TYPES,
    SIGNED_INTEGER_TYPES,
    UNSIGNED_INTEGER_TYPES,
    parse_bytes_m_info,
    parse_decimal_info,
    parse_integer_typeinfo,
)

# from vyper.exceptions import InvalidLiteral, InvalidType, OverflowException, TypeMismatch
from vyper.utils import DECIMAL_DIVISOR, MAX_DECIMAL_PLACES, SizeLimits, checksum_encode, int_bounds

DECIMAL_BITS = 168
ADDRESS_BITS = 160
TEST_TYPES = BASE_TYPES.union({"Bytes[32]"})

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
        return parse_bytes_m_info(type_).m
    if type_.startswith("Bytes"):
        return int(type_[6:-1])
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
    elif type_ == "bool":
        return 1
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


def can_convert(o_typ, i_typ):
    """
    Checks whether conversion from one type to another is valid.
    """
    it = _get_case_type(i_typ)
    ot = _get_case_type(o_typ)

    # Skip bytes20 because they are treated as addresses
    if it == "bytes" and _get_type_N(i_typ) == 20:
        return False

    # Check

    if ot == "bool":
        return it in ["int", "uint", "decimal", "bytes", "Bytes", "address"]

    elif ot == "int":
        return it in ["uint", "decimal", "bytes", "Bytes", "bool"]

    elif ot == "uint":
        return it in ["uint", "decimal", "bytes", "Bytes", "address", "bool"]

    elif ot == "decimal":
        return it in ["int", "uint", "bytes", "Bytes", "bool"]

    elif ot == "bytes":
        ot_bytes_info = parse_bytes_m_info(o_typ)
        if it == "Bytes":
            # bytesN must be of equal or larger size to Bytes[M]
            return ot_bytes_info.m >= _get_type_N(i_typ)
        elif it == "address":
            return ot_bytes_info.m_bits >= ADDRESS_BITS
        return it in ["decimal", "Bytes", "address"]

    elif ot == "Bytes":
        return it in ["int", "uint", "decimal", "address"]

    elif ot == "address":
        return it in ["bool", "uint", "bytes"]


def extract_io_value(o_typ, i_typ, input_val):
    """
    Modify the test case if necessary, and generate the expected value.
    Returns a tuple of (test_case, expected_value).
    """

    it = _get_case_type(i_typ)
    ot = _get_case_type(o_typ)

    output_val = None

    # Extract relevant info

    if it in ["int", "uint"]:
        it_int_info = parse_integer_typeinfo(i_typ)

    if ot in ["int", "uint"]:
        ot_int_info = parse_integer_typeinfo(o_typ)

    # if it == "decimal":
    #    it_dec_info = parse_decimal_info(i_typ)

    if ot == "decimal":
        ot_dec_info = parse_decimal_info(o_typ)

    if it == "bytes":
        it_bytes_info = parse_bytes_m_info(i_typ)

    if ot == "bytes":
        ot_bytes_info = parse_bytes_m_info(o_typ)

    # Manipulate input value and convert
    if ot in ["int", "uint"]:

        if it in ["int", "uint"]:
            (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
            input_val = output_val = clamp(ot_lo, ot_hi, input_val)

        if it == "decimal":
            # Clamp
            (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
            input_val_clamped = clamp(ot_lo, ot_hi, Decimal(input_val))
            input_val = format(Decimal(input_val_clamped), f".{MAX_DECIMAL_PLACES}f")
            output_val = int(input_val_clamped)

        if it == "bool":
            output_val = int(input_val)

        if it == "Bytes":
            in_bytes = _get_type_N(i_typ)
            in_bits = in_bytes * 8
            in_nibbles = _get_nibble(i_typ)
            out_nibbles = _get_nibble(o_typ)

            out_bytes = ot_int_info.bits // 8

            if in_bytes >= out_bytes:
                index = in_bytes - out_bytes
                largest_value_bytes = (2 ** (ot_int_info.bits - 1) - 1).to_bytes(
                    out_bytes, byteorder="big"
                )
                input_val = b"\x00" * index + largest_value_bytes

            if ot == "uint":
                output_val = int(input_val.hex(), 16) if input_val != b"" else 0

            elif ot == "int":
                if in_bytes >= out_bytes:
                    output_val = (
                        hex_to_signed_int(input_val.hex(), ot_int_info.bits)
                        if input_val != b""
                        else 0
                    )
                else:
                    output_val = (
                        hex_to_signed_int(input_val.hex(), in_bits) if input_val != b"" else 0
                    )

        elif it == "bytes":
            in_nibbles = _get_nibble(i_typ)
            out_nibbles = _get_nibble(o_typ)
            if ot == "uint":
                if in_nibbles > out_nibbles:
                    # Clamp input value
                    index = in_nibbles - out_nibbles + 2
                    input_val = add_0x_prefix("0" * (index - 2) + input_val[index:])

                output_val = int(input_val, 16)

            elif ot == "int":
                if it_bytes_info.m_bits >= ot_int_info.bits:
                    index = (in_nibbles - out_nibbles) + 2
                    largest_value_hex = hex(2 ** (ot_int_info.bits - 1) - 1)

                    input_val = add_0x_prefix("0" * (index - 2) + largest_value_hex[2:])
                    output_val = hex_to_signed_int(input_val, ot_int_info.bits)
                else:
                    output_val = hex_to_signed_int(input_val, it_bytes_info.m_bits)

    if ot == "uint" and it == "address":
        in_nibbles = _get_nibble(i_typ)
        out_nibbles = _get_nibble(o_typ)

        (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
        output_val = clamp(ot_lo, ot_hi, int(input_val, 16))
        # Value should always give a valid address after clamping
        input_val = checksum_encode(decode_single("address", encode_single(o_typ, output_val)))

    if ot == "bytes":
        out_nibbles = _get_nibble(o_typ)
        if it in ["int", "uint"]:
            # Input must have fewer than M bytes set
            if ot_bytes_info.m_bits < it_int_info.bits:
                (ot_lo, ot_hi) = int_bounds(it_int_info.is_signed, ot_int_info.m_bits)
                input_val = clamp(ot_lo, ot_hi, input_val)

            if it_int_info.is_signed:
                msb = "f" if input_val < 0 else "0"
                output_hex_str = remove_0x_prefix(
                    signed_int_to_hex(input_val, it_int_info.bits)
                ).rjust(ot_bytes_info.m, msb)
            else:
                output_hex_str = remove_0x_prefix(hex(input_val)).rjust(out_nibbles, "0")

        elif it == "decimal":

            output_hex_str = signed_int_to_hex(int(Decimal(input_val) * DECIMAL_DIVISOR), 256)[
                2:
            ].rjust(64, "0")
            if out_nibbles < 64:
                index = 64 - (out_nibbles)
                output_hex_str = output_hex_str[index:]

        elif it == "Bytes":
            output_hex_str = input_val.hex().ljust(out_nibbles, "0")

        elif it == "bool":
            output_hex_str = hex(int(input_val))[2].rjust(out_nibbles, "0")

        elif it == "address":
            output_hex_str = input_val[2:].rjust(out_nibbles, "0")

        output_val = bytes.fromhex(output_hex_str)

    if ot == "address":
        # Modify input value by clamping to 160 bits
        in_nibbles = _get_nibble(i_typ)
        out_nibbles = _get_nibble(o_typ)
        index = 2 if in_nibbles <= out_nibbles else in_nibbles - out_nibbles + 2

        if it == "uint":
            output_hex_str = hex(input_val)[index:].rjust(out_nibbles, "0")
            input_val = int(add_0x_prefix("0" * (index - 2) + hex(input_val)[index:]), 16)

        elif it == "bytes":
            output_hex_str = input_val[index:].rjust(out_nibbles, "0")
            input_val = add_0x_prefix("0" * (index - 2) + input_val[index:])

        elif it == "Bytes":
            index = index - 2  # Remove the 0x
            output_hex_str = input_val.hex()[index:].rjust(out_nibbles, "0")
            input_val = b"\x00" * (index // 2) + input_val[index // 2 :]

        elif it == "bool":
            output_hex_str = hex(int(input_val))[2].rjust(out_nibbles, "0")

        output_val = checksum_encode(add_0x_prefix(output_hex_str))

    if ot == "bool":

        if it in ["int", "uint"]:
            output_val = input_val != 0

        elif it == "decimal":
            output_val = Decimal(input_val) != 0

        elif it == "bytes":
            output_val = int(input_val, 16) != 0

        elif it == "Bytes":
            output_val = bool(int(input_val.hex(), 16)) if input_val != b"" else False

        elif it == "address":
            output_val = False if input_val == ZERO_ADDRESS else True

    if ot == "decimal":

        if it in ["int", "uint"]:

            input_val = clamp(
                math.ceil(SizeLimits.MIN_AST_DECIMAL),
                math.floor(SizeLimits.MAX_AST_DECIMAL),
                input_val,
            )
            output_val = Decimal(input_val)

        elif it == "bool":
            output_val = Decimal(input_val)

        elif it == "bytes":
            in_nibbles = _get_nibble(i_typ)
            if it_bytes_info.m_bits > ot_dec_info.bits:
                # Clamp input value
                index = in_nibbles - (ot_dec_info.bits // 4) + 2

                # Manually set to largest decimal prefix
                input_val = add_0x_prefix("0" * (index - 2) + "7" + input_val[index + 1 :])

            output_val = (
                Decimal(hex_to_signed_int(input_val, it_bytes_info.m_bits)) / DECIMAL_DIVISOR
            )

        elif it == "Bytes":
            in_bytes = _get_type_N(i_typ)
            in_bits = in_bytes * 8
            if input_val == b"":
                output_val = Decimal("0")
            else:
                input_val_raw_before = (
                    Decimal(hex_to_signed_int(input_val.hex(), in_bits)) / DECIMAL_DIVISOR
                )
                # Validate input is within bounds
                input_val_raw_after = clamp(
                    SizeLimits.MIN_AST_DECIMAL, SizeLimits.MAX_AST_DECIMAL, input_val_raw_before
                )
                if input_val_raw_after != input_val_raw_before:
                    input_val = encode_single("fixed168x10", input_val_raw_after)[-in_bytes:]
                output_val = input_val_raw_after

    return input_val, output_val


def generate_default_cases_for_in_type(i_typ):
    """
    Generate the default test cases based on input type only.
    Test cases may be subsequently modified in `extract_io_value()`.
    """

    it = _get_case_type(i_typ)

    # Generate default cases based on input type only
    if it in ("int", "uint"):
        it_int_info = parse_integer_typeinfo(i_typ)
        (it_lo, it_hi) = int_bounds(it_int_info.is_signed, it_int_info.bits)

        if it_int_info.is_signed:
            return [it_lo, it_lo + 1, -1, 0, 1, it_hi - 1, it_hi]
        else:
            fixed_pt = 2 ** (it_int_info.bits - 1)
            return [0, 1, it_hi - 1, it_hi, fixed_pt]

    elif it == "decimal":
        return [
            format(SizeLimits.MIN_AST_DECIMAL, f".{MAX_DECIMAL_PLACES}f"),
            "-0.0000000001",
            "-0.9999999999",
            "-1.0",
            "0.0",
            "0.0000000001",
            "0.9999999999",
            "1.0",
            format(SizeLimits.MAX_AST_DECIMAL, f".{MAX_DECIMAL_PLACES}f"),
        ]

    elif it == "bytes":
        it_bytes_info = parse_bytes_m_info(i_typ)
        return [
            add_0x_prefix("00" * it_bytes_info.m),
            add_0x_prefix("00" * (it_bytes_info.m - 1) + "01"),
            add_0x_prefix("FF" * (it_bytes_info.m - 1) + "FE"),
            add_0x_prefix("FF" * it_bytes_info.m),
        ]

    elif it == "Bytes":
        bytes_N = _get_type_N(i_typ)
        return [
            b"",
            b"\x00",
            b"\x00" * bytes_N,
            b"\x01",
            b"\x00\x01",
            b"\xff" * (bytes_N - 1) + b"\xfe",
            b"\xff" * bytes_N,
        ]

    elif it == "bool":
        return [True, False]

    elif it == "address":
        return [
            ZERO_ADDRESS,
            ONE_ADDRESS,
            "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7",
            "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
        ]

    return []


def generate_passing_test_cases_for_pair(o_typ, i_typ):
    """
    Helper function to generate passing test cases for a pair of types.
    """
    res = []
    cases = generate_default_cases_for_in_type(i_typ)

    # Manipulate default cases and generate output values
    for c in cases:
        (input_val, expected_val) = extract_io_value(o_typ, i_typ, c)

        if expected_val is None:
            continue

        input_values = {
            "in_type": i_typ,
            "out_type": o_typ,
            "in_value": input_val,
            "out_value": expected_val,
        }

        # Check for duplicates after manipulating input value
        if input_values not in res:
            res.append(input_values)

    return res


def generate_passing_test_cases(type_pairs):
    """
    Helper function to generate passing test cases for a list of pairs.
    Checks if the conversion is valid.
    """
    res = []

    for tp in type_pairs:

        # Exclude uint to int conversions due to bug causing excessive number of errors
        # TODO: Remove once fixed
        if tp[0].startswith("int") and tp[1].startswith("uint"):
            continue

        if can_convert(tp[0], tp[1]):
            res += generate_passing_test_cases_for_pair(tp[0], tp[1])

    return res


@pytest.mark.parametrize(
    "input_values", generate_passing_test_cases(list(permutations(TEST_TYPES, 2)))
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

    if in_type.startswith(("bytes", "Bytes")) and out_type.startswith(("int", "uint", "decimal")):
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

    if in_type.startswith("address") and out_type == "bytes20":
        # Skip because raw address value is treated as bytes20
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
