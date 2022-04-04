from decimal import Decimal
from itertools import permutations

import pytest
from eth_abi import decode_single, encode_single
from eth_utils import add_0x_prefix, clamp, remove_0x_prefix
from web3.exceptions import ValidationError

from vyper.codegen.types import (
    BASE_TYPES,
    BYTES_M_TYPES,
    DECIMAL_TYPES,
    INTEGER_TYPES,
    SIGNED_INTEGER_TYPES,
    UNSIGNED_INTEGER_TYPES,
    parse_bytes_m_info,
    parse_decimal_info,
    parse_integer_typeinfo,
)
from vyper.exceptions import InvalidLiteral, InvalidType, OverflowException, TypeMismatch
from vyper.utils import (
    DECIMAL_DIVISOR,
    MAX_DECIMAL_PLACES,
    SizeLimits,
    bytes_to_int,
    checksum_encode,
    hex_to_int,
    int_bounds,
    round_towards_zero,
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
    """
    Helper function to convert a hex value to signed integer
    """
    val = hex_to_int(hexstr)
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


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


def can_convert(o_typ, i_typ):
    """
    Checks whether conversion from one type to another is valid.
    """
    it = _get_case_type(i_typ)
    ot = _get_case_type(o_typ)

    # Skip bytes20 because they are treated as addresses
    if i_typ == "bytes20":
        return False

    # Check
    if ot == "bool":
        return it in ["int", "uint", "decimal", "bytes", "Bytes", "address"]

    elif ot == "int":
        return it in ["uint", "decimal", "bytes", "Bytes", "bool"]

    elif ot == "uint":
        return it in ["int", "decimal", "bytes", "Bytes", "address", "bool"]

    elif ot == "decimal":
        return it in ["int", "uint", "bytes", "Bytes", "bool"]

    elif ot == "bytes":
        ot_bytes_info = parse_bytes_m_info(o_typ)
        if it in ["int", "uint"]:
            # bytesN must be of equal or larger size to [u]intM
            it_int_info = parse_integer_typeinfo(i_typ)
            return ot_bytes_info.m_bits >= it_int_info.bits
        elif it == "Bytes":
            # bytesN must be of equal or larger size to Bytes[M]
            return ot_bytes_info.m >= _get_type_N(i_typ)
        elif it == "address":
            return ot_bytes_info.m_bits >= ADDRESS_BITS
        return it in ["decimal", "Bytes", "address"]

    elif ot == "Bytes":
        return it in ["int", "uint", "decimal", "address"]

    elif ot == "address":
        return it in ["uint", "bytes", "Bytes"]


def generate_valid_input_output_values(o_typ, i_typ, input_val):
    """
    Modify the test case if necessary, and generate the expected value.
    Returns a tuple of (test_case, expected_value).
    """

    it = _get_case_type(i_typ)
    ot = _get_case_type(o_typ)

    output_val = None

    # Extract relevant info
    if it == "Bytes":
        in_bytes = _get_type_N(i_typ)

    if ot == "Bytes":
        out_bytes = _get_type_N(o_typ)

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
                input_val = add_0x_prefix(
                    encode_single(o_typ, output_val)[-it_bytes_info.m :].hex()
                )

    if ot == "uint" and it == "address":
        (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)
        output_val = clamp(ot_lo, ot_hi, hex_to_int(input_val))
        # Value should always give a valid address after clamping
        input_val = checksum_encode(decode_single("address", encode_single(o_typ, output_val)))

    if ot == "bytes":
        if it in ["int", "uint"]:
            # Input must have fewer than M bytes set
            (ot_lo, ot_hi) = int_bounds(it_int_info.is_signed, ot_bytes_info.m_bits)
            input_val = clamp(ot_lo, ot_hi, input_val)
            output_val = encode_single(i_typ, input_val)[-ot_bytes_info.m :]

        elif it == "decimal":
            input_val_raw = int(Decimal(input_val) * DECIMAL_DIVISOR)
            # If output byteN size is smaller than decimal, clamp to byte size.
            if ot_bytes_info.m_bits <= DECIMAL_BITS:
                (ot_lo, ot_hi) = int_bounds(True, ot_bytes_info.m_bits)
                input_val_clamped = clamp(ot_lo, ot_hi, input_val_raw)
                input_val = format(
                    Decimal(input_val_clamped) / DECIMAL_DIVISOR, f".{MAX_DECIMAL_PLACES}f"
                )

            output_val = encode_single("fixed168x10", Decimal(input_val))[-ot_bytes_info.m :]

        elif it == "Bytes":
            output_val = input_val.ljust(ot_bytes_info.m, b"\x00")

        elif it in ["address", "bool"]:
            output_val = encode_single(i_typ, input_val)[-ot_bytes_info.m :]

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
                encode_single("uint160", input_val_clamped)[-it_bytes_info.m :].hex()
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

        output_val = checksum_encode(
            decode_single("address", encode_single("uint160", input_val_clamped))
        )

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
                round_towards_zero(SizeLimits.MIN_AST_DECIMAL),
                round_towards_zero(SizeLimits.MAX_AST_DECIMAL),
                input_val,
            )
            output_val = Decimal(input_val)

        elif it == "bool":
            output_val = Decimal(input_val)

        elif it == "bytes":
            if it_bytes_info.m_bits > ot_dec_info.bits:
                # Clamp input value
                input_val = clamp(
                    round_towards_zero(SizeLimits.MIN_AST_DECIMAL),
                    round_towards_zero(SizeLimits.MAX_AST_DECIMAL),
                    Decimal(hex_to_signed_int(input_val, it_bytes_info.m_bits)) / DECIMAL_DIVISOR,
                )
                input_val = add_0x_prefix(
                    encode_single("fixed168x10", input_val)[-it_bytes_info.m :].hex()
                )

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
    Test cases may be subsequently modified in `generate_valid_input_output_values()`.
    """

    it = _get_case_type(i_typ)

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
            add_0x_prefix("7F" + "FF" * (it_bytes_info.m - 1)),
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
            b"\x7f" + b"\xff" * (bytes_N - 1),
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
        (input_val, expected_val) = generate_valid_input_output_values(o_typ, i_typ, c)

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
        if not tp[0].startswith("decimal") and not tp[1].startswith("bytes"):
            continue
        if can_convert(tp[0], tp[1]):
            res += generate_passing_test_cases_for_pair(tp[0], tp[1])

    return res


@pytest.mark.parametrize(
    "input_values", generate_passing_test_cases(list(permutations(TEST_TYPES, 2)))
)
@pytest.mark.fuzzing
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
        # Raw bytes are treated as uint256
        skip_c1 = True

    if in_type.startswith(("int", "uint")) and out_type.startswith("bytes"):
        # Skip conversion of integer literals because they are of uint256 / int256
        # types, unless it is bytes32
        if out_type != "bytes32":
            skip_c1 = True

    if in_type.startswith("Bytes") and out_type.startswith("bytes"):
        # Skip if length of Bytes[N] is same as size of bytesM
        if len(in_value) == parse_bytes_m_info(out_type).m:
            skip_c1 = True

    if in_type.startswith("bytes") and parse_bytes_m_info(in_type).m != 32:
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
        assert c2.test_input_convert(Decimal(in_value)) == out_value
    elif out_type == "decimal":
        assert c2.test_input_convert(in_value) == Decimal(out_value)
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

    if out_type == "decimal":
        assert c3.test_state_variable_convert() == Decimal(out_value)
    else:
        assert c3.test_state_variable_convert() == out_value

    contract_4 = f"""

@external
def test_state_variable_convert() -> {out_type}:
    bar: {in_type} = {in_value}
    return convert(bar, {out_type})
    """

    c4 = get_contract_with_gas_estimation(contract_4)

    if out_type == "decimal":
        assert c4.test_state_variable_convert() == Decimal(out_value)
    else:
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

    # uint256 conversion is currently valid due to type inference on literals
    # not quite working yet
    for t in TEST_TYPES.difference({"uint256"}):
        case = generate_default_cases_for_in_type(t)[0]
        res.append({"in_type": t, "out_type": t, "in_value": case, "exception": InvalidType})

    return res


def generate_test_cases_for_byte_array_type_mismatch():
    """
    Helper function to generate test cases for invalid conversion of byte arrays
    greater than 32 in size.
    """
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
    """
    Helper function to generate invalid numeric conversions:
    1. Negative numbers to uint
    2. Input value is out of bounds of the output type
    """
    res = []

    for tp in list(permutations(INTEGER_TYPES.union(DECIMAL_TYPES), 2)):

        o_typ = tp[0]
        i_typ = tp[1]

        ot = _get_case_type(o_typ)
        it = _get_case_type(i_typ)

        if ot == it:
            continue

        cases = generate_default_cases_for_in_type(i_typ)

        # Cast decimals to numeric value
        if it == "decimal":
            cases = [Decimal(c) for c in cases]

        # Extract numeric bounds
        if ot in ["int", "uint"]:
            ot_int_info = parse_integer_typeinfo(o_typ)
            (ot_lo, ot_hi) = int_bounds(ot_int_info.is_signed, ot_int_info.bits)

        # Filter for invalid test cases
        if ot in ["int", "uint"]:
            cases = [c for c in cases if (c < ot_lo or c > ot_hi)]

        elif ot == "decimal":
            cases = [
                c
                for c in cases
                if (c < SizeLimits.MIN_AST_DECIMAL or c > SizeLimits.MAX_AST_DECIMAL)
            ]

        for c in cases:
            # Cast decimal values back to string
            if it == "decimal":
                c = format(c, f".{MAX_DECIMAL_PLACES}f")

            res.append(
                {
                    "in_type": i_typ,
                    "out_type": o_typ,
                    "in_value": c,
                    "exception": InvalidLiteral,
                }
            )

    return res


def generate_test_cases_for_clamped_address_conversion():
    """
    Helper function to generate conversions from valid types to address with
    too large a value (i.e. will be clamped).
    """
    res = []

    for u in UNSIGNED_INTEGER_TYPES:
        it_int_info = parse_integer_typeinfo(u)
        if it_int_info.bits > ADDRESS_BITS:
            cases = [
                MAX_ADDRESS_INT_VALUE + 1,
                2 ** it_int_info.bits - 1,
                2 ** (it_int_info.bits - 1),
            ]
            for c in cases:
                res.append(
                    {
                        "in_type": u,
                        "out_type": "address",
                        "in_value": c,
                        "exception": InvalidLiteral,
                    }
                )

    for b in BYTES_M_TYPES:
        it_bytes_info = parse_bytes_m_info(b)
        if it_bytes_info.m_bits > ADDRESS_BITS:
            cases = [
                add_0x_prefix(
                    encode_single("uint256", (MAX_ADDRESS_INT_VALUE + 1))[-it_bytes_info.m :].hex()
                ),
                add_0x_prefix((b"\xff" * it_bytes_info.m).hex()),
                add_0x_prefix((b"\xff" * (it_bytes_info.m - 1) + b"\xfe").hex()),
            ]
            for c in cases:
                res.append(
                    {
                        "in_type": b,
                        "out_type": "address",
                        "in_value": c,
                        "exception": None,
                    }
                )

    return res


def generate_test_cases_for_decimal_overflow():
    """
    Helper function to generate test cases for conversions from decimal to a valid
    type but with an overflow value.
    """
    res = []

    for t in TEST_TYPES.difference({"Bytes[32]", "address", "decimal"}):
        res.append(
            {
                "in_type": "decimal",
                "out_type": t,
                # Exceeds by 0.0000000001
                "in_value": "18707220957835557353007165858768422651595.9365500928",
                "exception": OverflowException,
            }
        )

    return res


INVALID_CONVERSIONS = (
    [
        # (in_type, out_type
        ("bool", "address"),
        ("decimal", "address"),
        ("address", "bytes4"),
        ("address", "bytes8"),
        ("address", "bytes12"),
        ("address", "bytes16"),
        ("address", "decimal"),
        ("bytes24", "decimal"),
        ("bytes28", "decimal"),
        ("bytes32", "decimal"),
    ]
    + [(i[1], "address") for i in enumerate(SIGNED_INTEGER_TYPES)]
    + [("address", i[1]) for i in enumerate(SIGNED_INTEGER_TYPES)]
)


def generate_test_cases_for_invalid_dislike_types_conversion():
    """
    Helper function to generate test cases for invalid dislike types conversions
    as specified in INVALID_CONVERSIONS.
    """
    res = []

    for tp in INVALID_CONVERSIONS:

        o_typ = tp[1]
        i_typ = tp[0]

        if can_convert(o_typ, i_typ):
            continue

        case = generate_default_cases_for_in_type(i_typ)[-1]

        res.append(
            {
                "in_type": i_typ,
                "out_type": o_typ,
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
    + generate_test_cases_for_clamped_address_conversion()
    + generate_test_cases_for_decimal_overflow()
    + generate_test_cases_for_invalid_dislike_types_conversion(),
)
@pytest.mark.fuzzing
def test_invalid_convert(
    get_contract_with_gas_estimation, assert_compile_failed, assert_tx_failed, input_values
):
    """
    Test multiple contracts and check for a specific exception.
    If no exception is provided, a runtime revert is expected (e.g. clamping).
    """

    in_type = input_values["in_type"]
    out_type = input_values["out_type"]
    in_value = input_values["in_value"]
    exception = input_values["exception"]

    skip_c2 = skip_c4 = False

    if in_type.startswith("int") and out_type == "address":
        skip_c2 = skip_c4 = True

    if in_type.startswith("bytes"):
        skip_c2 = skip_c4 = True

    if in_type == "address":
        skip_c2 = skip_c4 = True

    contract_1 = f"""
@external
def foo():
    bar: {in_type} = {in_value}
    foobar: {out_type} = convert(bar, {out_type})
    """

    if exception is None or exception in (InvalidLiteral,):
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

    if not skip_c2:
        if exception is None:
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

    if exception is None or exception in (InvalidLiteral, OverflowException):
        c3 = get_contract_with_gas_estimation(contract_3)
        if in_type == "decimal":

            if SizeLimits.MIN_AST_DECIMAL <= Decimal(in_value) <= SizeLimits.MAX_AST_DECIMAL:
                assert_tx_failed(lambda: c3.foo(Decimal(in_value)))

            else:
                # Overflow decimal throws ValidationError because it cannot be validated
                # based on ABI type "fixed168x10"
                with pytest.raises(ValidationError):
                    assert_tx_failed(lambda: c3.foo(Decimal(in_value)))

        else:
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

    if not skip_c4:
        if exception is None:
            c4 = get_contract_with_gas_estimation(contract_4)
            assert_tx_failed(lambda: c4.foo())

        else:
            assert_compile_failed(
                lambda: get_contract_with_gas_estimation(contract_4),
                exception,
            )
