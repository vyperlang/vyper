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
from vyper.utils import (
    DECIMAL_DIVISOR,
    MAX_DECIMAL_PLACES,
    SizeLimits,
    bytes_to_int,
    checksum_encode,
    hex_to_int,
    int_bounds,
)

DECIMAL_BITS = 168
ADDRESS_BITS = 160
TEST_TYPES = BASE_TYPES.union({"Bytes[32]"})

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ONE_ADDRESS = "0x0000000000000000000000000000000000000001"
MAX_ADDRESS = "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF"
MAX_ADDRESS_INT_VALUE = hex_to_int(MAX_ADDRESS)
MIN_ADDRESS_INT_VALUE = hex_to_int(ZERO_ADDRESS)


def hex_to_signed_int(hexstr, bits):
    val = hex_to_int(hexstr)
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
        return it in ["uint", "bytes", "Bytes"]


def extract_io_value(o_typ, i_typ, input_val):
    """
    Modify the test case if necessary, and generate the expected value.
    Returns a tuple of (test_case, expected_value).
    """

    it = _get_case_type(i_typ)
    ot = _get_case_type(o_typ)

    output_val = None

    # Extract relevant info

    in_nibbles = _get_nibble(i_typ)
    out_nibbles = _get_nibble(o_typ)

    if it in ["int", "uint"]:
        it_int_info = parse_integer_typeinfo(i_typ)

    if ot in ["int", "uint"]:
        ot_int_info = parse_integer_typeinfo(o_typ)

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

        elif it == "decimal":
            # Clamp
            (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
            input_val_clamped = clamp(ot_lo, ot_hi, Decimal(input_val))
            input_val = format(Decimal(input_val_clamped), f".{MAX_DECIMAL_PLACES}f")
            output_val = int(input_val_clamped)

        elif it == "bool":
            output_val = int(input_val)

        elif it == "Bytes":
            in_bytes = _get_type_N(i_typ)
            in_bits = in_bytes * 8
            out_bytes = ot_int_info.bits // 8

            # Default output value
            output_val = (
                hex_to_signed_int(input_val.hex(), in_bits)
                if ot_int_info.is_signed
                else bytes_to_int(input_val)
            )

            # If input Bytes[N] is greater than output integer size, clamp to integer size
            if in_bytes >= out_bytes:
                (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
                # Override output value with clamped value
                output_val = clamp(ot_lo, ot_hi, output_val)
                input_val = encode_single(o_typ, output_val)[-in_bytes:]

        elif it == "bytes":

            # Default output value
            output_val = (
                hex_to_signed_int(input_val, it_bytes_info.m_bits)
                if ot_int_info.is_signed
                else hex_to_int(input_val)
            )

            # Clamp to output integer size if input byte size is greater
            if it_bytes_info.m_bits >= ot_int_info.bits:
                (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
                # Override default output value with clamped value
                output_val = clamp(ot_lo, ot_hi, output_val)
                input_val = add_0x_prefix(encode_single(o_typ, output_val).hex()[-in_nibbles:])

    if ot == "uint" and it == "address":
        (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
        output_val = clamp(ot_lo, ot_hi, hex_to_int(input_val))
        # Value should always give a valid address after clamping
        input_val = checksum_encode(decode_single("address", encode_single(o_typ, output_val)))

    if ot == "bytes":
        if it in ["int", "uint"]:
            # Input must have fewer than M bytes set
            (ot_lo, ot_hi) = int_bounds(it_int_info.is_signed, ot_int_info.m_bits)
            input_val = clamp(ot_lo, ot_hi, input_val)
            output_hex_str = encode_single(i_typ, input_val).hex()[-out_nibbles:]

        elif it == "decimal":
            input_val_raw = int(Decimal(input_val) * DECIMAL_DIVISOR)
            # If output byteN size is smaller than decimal, clamp to byte size.
            if ot_bytes_info.m_bits <= DECIMAL_BITS:
                (ot_lo, ot_hi) = int_bounds(True, ot_bytes_info.m_bits)
                input_val_clamped = clamp(ot_lo, ot_hi, input_val_raw)
                input_val = format(
                    Decimal(input_val_clamped) / DECIMAL_DIVISOR, f".{MAX_DECIMAL_PLACES}f"
                )

            output_hex_str = encode_single("fixed168x10", Decimal(input_val)).hex()[-out_nibbles:]

        elif it == "Bytes":
            output_hex_str = input_val.hex().ljust(out_nibbles, "0")

        elif it == "bool":
            output_hex_str = remove_0x_prefix(hex(int(input_val))).rjust(out_nibbles, "0")

        elif it == "address":
            output_hex_str = remove_0x_prefix(input_val).rjust(out_nibbles, "0")

        output_val = bytes.fromhex(output_hex_str)

    if ot == "address":
        # Modify input value by clamping to the max address value
        if it == "uint":
            input_val = input_val_clamped = clamp(
                MIN_ADDRESS_INT_VALUE, MAX_ADDRESS_INT_VALUE, input_val
            )

        elif it == "bytes":
            input_val_clamped = clamp(
                MIN_ADDRESS_INT_VALUE, MAX_ADDRESS_INT_VALUE, hex_to_int(input_val)
            )
            input_val = add_0x_prefix(
                remove_0x_prefix(hex(input_val_clamped)).rjust(in_nibbles, "0")
            )

        elif it == "Bytes":
            in_N = _get_type_N(i_typ)
            input_val_clamped = clamp(
                MIN_ADDRESS_INT_VALUE, MAX_ADDRESS_INT_VALUE, bytes_to_int(input_val)
            )
            # Need to cast hex value to at least 2 digits so that single char hex
            # values do not throw for hex() e.g. 0x1, 0x0
            input_val = bytes.fromhex(remove_0x_prefix(hex(input_val_clamped)).rjust(2, "0")).rjust(
                in_N, b"\x00"
            )

        output_hex_str = remove_0x_prefix(hex(input_val_clamped))
        output_val = checksum_encode(add_0x_prefix(output_hex_str.rjust(out_nibbles, "0")))

    if ot == "bool":

        if it in ["int", "uint"]:
            output_val = input_val != 0

        elif it == "decimal":
            output_val = Decimal(input_val) != 0

        elif it == "bytes":
            output_val = hex_to_int(input_val) != 0

        elif it == "Bytes":
            output_val = bool(hex_to_int(input_val.hex())) if input_val != b"" else False

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
            if it_bytes_info.m_bits > ot_dec_info.bits:
                # Clamp input value
                index = in_nibbles - (ot_dec_info.bits // 4) + 2
                # Manually set to largest decimal prefix in bits
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
                # Convert Bytes to raw integer value, clamp and then convert to decimal
                output_val = clamp(
                    SizeLimits.MIN_AST_DECIMAL,
                    SizeLimits.MAX_AST_DECIMAL,
                    Decimal(hex_to_signed_int(input_val.hex(), in_bits)) / DECIMAL_DIVISOR,
                )
                input_val = encode_single("fixed168x10", output_val)[-in_bytes:]

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
            MAX_ADDRESS,
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

        # if tp[0].startswith("int") and tp[1].startswith("uint"):
        #    continue

        # if not tp[0].startswith("bytes") and not tp[1].startswith("decimal"):
        #    continue

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
