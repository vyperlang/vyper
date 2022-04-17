import binascii
import decimal
import sys
import traceback
from typing import Any, Dict, List, Union

from vyper.exceptions import DecimalOverrideException, InvalidLiteral


class DecimalContextOverride(decimal.Context):
    def __setattr__(self, name, value):
        if name == "prec":
            # CMC 2022-03-27: should we raise a warning instead of an exception?
            raise DecimalOverrideException("Overriding decimal precision disabled")
        super().__setattr__(name, value)


decimal.setcontext(DecimalContextOverride(prec=78))


try:
    from Crypto.Hash import keccak  # type: ignore

    keccak256 = lambda x: keccak.new(digest_bits=256, data=x).digest()  # noqa: E731
except ImportError:
    import sha3 as _sha3

    keccak256 = lambda x: _sha3.sha3_256(x).digest()  # noqa: E731

try:
    # available py3.8+
    from functools import cached_property
except ImportError:
    from cached_property import cached_property  # type: ignore


# Converts four bytes to an integer
def fourbytes_to_int(inp):
    return (inp[0] << 24) + (inp[1] << 16) + (inp[2] << 8) + inp[3]


def signed_to_unsigned(int_, bits):
    """
    Reinterpret a signed integer with n bits as an unsigned integer.
    The implementation is unforgiving in that it assumes the input is in
    bounds for int<bits>, in order to fail more loudly (and not hide
    errors in modular reasoning in consumers of this function).
    """
    if int_ < 0:
        return int_ + 2 ** bits
    return int_


def unsigned_to_signed(int_, bits):
    """
    Reinterpret an unsigned integer with n bits as a signed integer.
    The implementation is unforgiving in that it assumes the input is in
    bounds for uint<bits>, in order to fail more loudly (and not hide
    errors in modular reasoning in consumers of this function).
    """
    if int_ > (2 ** (bits - 1)) - 1:
        return int_ - (2 ** bits)
    return int_


# utility function for debugging purposes
def trace(n=5, out=sys.stderr):
    print("BEGIN TRACE", file=out)
    for x in list(traceback.format_stack())[-n:]:
        print(x.strip(), file=out)
    print("END TRACE", file=out)


# converts a signature like Func(bool,uint256,address) to its 4 byte method ID
# TODO replace manual calculations in codebase with this
def abi_method_id(method_sig):
    return fourbytes_to_int(keccak256(bytes(method_sig, "utf-8"))[:4])


# map a string to only-alphanumeric chars
def mkalphanum(s):
    return "".join([c if c.isalnum() else "_" for c in s])


def round_towards_zero(d: decimal.Decimal) -> int:
    # TODO double check if this can just be int(d)
    # (but either way keep this util function bc it's easier at a glance
    # to understand what round_towards_zero() does instead of int())
    return int(d.to_integral_exact(decimal.ROUND_DOWN))


# Converts string to bytes
def string_to_bytes(str):
    bytez = b""
    for c in str:
        if ord(c) >= 256:
            raise InvalidLiteral(f"Cannot insert special character {c} into byte array")
        bytez += bytes([ord(c)])
    bytez_length = len(bytez)
    return bytez, bytez_length


# Converts a provided hex string to an integer
def hex_to_int(inp):
    if inp[:2] == "0x":
        inp = inp[2:]
    return bytes_to_int(binascii.unhexlify(inp))


# Converts bytes to an integer
def bytes_to_int(bytez):
    o = 0
    for b in bytez:
        o = o * 256 + b
    return o


def is_checksum_encoded(addr):
    return addr == checksum_encode(addr)


# Encodes an address using ethereum's checksum scheme
def checksum_encode(addr):  # Expects an input of the form 0x<40 hex chars>
    assert addr[:2] == "0x" and len(addr) == 42, addr
    o = ""
    v = bytes_to_int(keccak256(addr[2:].lower().encode("utf-8")))
    for i, c in enumerate(addr[2:]):
        if c in "0123456789":
            o += c
        else:
            o += c.upper() if (v & (2 ** (255 - 4 * i))) else c.lower()
    return "0x" + o


# Returns lowest multiple of 32 >= the input
def ceil32(x):
    return x if x % 32 == 0 else x + 32 - (x % 32)


# Calculates amount of gas needed for memory expansion
def calc_mem_gas(memsize):
    return (memsize // 32) * 3 + (memsize // 32) ** 2 // 512


# Specific gas usage
GAS_IDENTITY = 15
GAS_IDENTITYWORD = 3
GAS_CODECOPY_WORD = 3
GAS_CALLDATACOPY_WORD = 3

# A decimal value can store multiples of 1/DECIMAL_DIVISOR
MAX_DECIMAL_PLACES = 10
DECIMAL_DIVISOR = 10 ** MAX_DECIMAL_PLACES


def int_bounds(signed, bits):
    """
    calculate the bounds on an integer type
    ex. int_bounds(8, True) -> (-128, 127)
        int_bounds(8, False) -> (0, 255)
    """
    if signed:
        return -(2 ** (bits - 1)), (2 ** (bits - 1)) - 1
    return 0, (2 ** bits) - 1


# EVM div semantics as a python function
def evm_div(x, y):
    if y == 0:
        return 0
    # doesn't actually work:
    # return int(x / y)
    # NOTE: should be same as: round_towards_zero(Decimal(x)/Decimal(y))
    sign = -1 if (x * y) < 0 else 1
    return sign * (abs(x) // abs(y))  # adapted from py-evm


# EVM mod semantics as a python function
def evm_mod(x, y):
    if y == 0:
        return 0

    # this doesn't actually work when num digits exceeds fp precision:
    # return int(math.fmod(x, y))
    sign = -1 if x < 0 else 1
    return sign * (abs(x) % abs(y))  # adapted from py-evm


# memory used for system purposes, not for variables
class MemoryPositions:
    FREE_VAR_SPACE = 0
    FREE_VAR_SPACE2 = 32
    RESERVED_MEMORY = 64


# Sizes of different data types. Used to clamp types.
class SizeLimits:
    MAX_INT128 = 2 ** 127 - 1
    MIN_INT128 = -(2 ** 127)
    MAX_INT256 = 2 ** 255 - 1
    MIN_INT256 = -(2 ** 255)
    MAXDECIMAL = 2 ** 167 - 1  # maxdecimal as EVM value
    MINDECIMAL = -(2 ** 167)  # mindecimal as EVM value
    # min decimal allowed as Python value
    MIN_AST_DECIMAL = -decimal.Decimal(2 ** 167) / DECIMAL_DIVISOR
    # max decimal allowed as Python value
    MAX_AST_DECIMAL = decimal.Decimal(2 ** 167 - 1) / DECIMAL_DIVISOR
    MAX_UINT8 = 2 ** 8 - 1
    MAX_UINT256 = 2 ** 256 - 1

    @classmethod
    def in_bounds(cls, type_str, value):
        # TODO: fix this circular import
        from vyper.codegen.types import parse_decimal_info, parse_integer_typeinfo

        assert isinstance(type_str, str)
        if type_str == "decimal":
            info = parse_decimal_info(type_str)
        else:
            info = parse_integer_typeinfo(type_str)

        (lo, hi) = int_bounds(info.is_signed, info.bits)
        return lo <= value <= hi


# Otherwise reserved words that are whitelisted for function declarations
FUNCTION_WHITELIST = {
    "send",
}

# List of valid IR macros.
# TODO move this somewhere else, like ir_node.py
VALID_IR_MACROS = {
    "assert",
    "break",
    "iload",
    "istore",
    "dload",
    "dloadbytes",
    "ceil32",
    "clamp",
    "clamp_nonzero",
    "clampge",
    "clampgt",
    "clample",
    "clamplt",
    "continue",
    "debugger",
    "ge",
    "if",
    "select",
    "le",
    "deploy",
    "ne",
    "pass",
    "repeat",
    "seq",
    "set",
    "sge",
    "sha3_32",
    "sha3_64",
    "sle",
    "uclamp",
    "uclampge",
    "uclampgt",
    "uclample",
    "uclamplt",
    "with",
    "label",
    "goto",
    "~extcode",
    "~selfcode",
    "~calldata",
    "~empty",
    "var_list",
}


def indent(text: str, indent_chars: Union[str, List[str]] = " ", level: int = 1) -> str:
    """
    Indent lines of text in the string ``text`` using the indentation
    character(s) given in ``indent_chars`` ``level`` times.

    :param text: A string containing the lines of text to be indented.
    :param level: The number of times to indent lines in ``text``.
    :param indent_chars: The characters to use for indentation.  If a string,
        uses repetitions of that string for indentation.  If a list of strings,
        uses repetitions of each string to indent each line.

    :return: The indented text.
    """
    text_lines = text.splitlines(keepends=True)

    if isinstance(indent_chars, str):
        indented_lines = [indent_chars * level + line for line in text_lines]
    elif isinstance(indent_chars, list):
        if len(indent_chars) != len(text_lines):
            raise ValueError("Must provide indentation chars for each line")

        indented_lines = [ind * level + line for ind, line in zip(indent_chars, text_lines)]
    else:
        raise ValueError("Unrecognized indentation characters value")

    return "".join(indented_lines)


def annotate_source_code(
    source_code: str,
    lineno: int,
    col_offset: int = None,
    context_lines: int = 0,
    line_numbers: bool = False,
) -> str:
    """
    Annotate the location specified by ``lineno`` and ``col_offset`` in the
    source code given by ``source_code`` with a location marker and optional
    line numbers and context lines.

    :param source_code: The source code containing the source location.
    :param lineno: The 1-indexed line number of the source location.
    :param col_offset: The 0-indexed column offset of the source location.
    :param context_lines: The number of contextual lines to include above and
        below the source location.
    :param line_numbers: If true, line numbers are included in the location
        representation.

    :return: A string containing the annotated source code location.
    """
    if lineno is None:
        return ""

    source_lines = source_code.splitlines(keepends=True)
    if lineno < 1 or lineno > len(source_lines):
        raise ValueError("Line number is out of range")

    line_offset = lineno - 1
    start_offset = max(0, line_offset - context_lines)
    end_offset = min(len(source_lines), line_offset + context_lines + 1)

    line_repr = source_lines[line_offset]
    if "\n" not in line_repr[-2:]:  # Handle certain edge cases
        line_repr += "\n"
    if col_offset is None:
        mark_repr = ""
    else:
        mark_repr = "-" * col_offset + "^" + "\n"

    before_lines = "".join(source_lines[start_offset:line_offset])
    after_lines = "".join(source_lines[line_offset + 1 : end_offset])
    location_repr = "".join((before_lines, line_repr, mark_repr, after_lines))

    if line_numbers:
        # Create line numbers
        lineno_reprs = [f"{i} " for i in range(start_offset + 1, end_offset + 1)]

        # Highlight line identified by `lineno`
        local_line_off = line_offset - start_offset
        lineno_reprs[local_line_off] = "---> " + lineno_reprs[local_line_off]

        # Calculate width of widest line no
        max_len = max(len(i) for i in lineno_reprs)

        # Justify all line nos according to this width
        justified_reprs = [i.rjust(max_len) for i in lineno_reprs]
        if col_offset is not None:
            justified_reprs.insert(local_line_off + 1, "-" * max_len)

        location_repr = indent(location_repr, indent_chars=justified_reprs)

    # Ensure no trailing whitespace and trailing blank lines are only included
    # if they are part of the source code
    if col_offset is None:
        # Number of lines doesn't include column marker line
        num_lines = end_offset - start_offset
    else:
        num_lines = end_offset - start_offset + 1

    cleanup_lines = [line.rstrip() for line in location_repr.splitlines()]
    cleanup_lines += [""] * (num_lines - len(cleanup_lines))

    return "\n".join(cleanup_lines)


def levenshtein_norm(source: str, target: str) -> float:
    """Calculates the normalized Levenshtein distance between two string
    arguments. The result will be a float in the range [0.0, 1.0], with 1.0
    signifying the biggest possible distance between strings with these lengths

    From jazzband/docopt-ng
    https://github.com/jazzband/docopt-ng/blob/bbed40a2335686d2e14ac0e6c3188374dc4784da/docopt.py
    """

    # Compute Levenshtein distance using helper function. The max is always
    # just the length of the longer string, so this is used to normalize result
    # before returning it
    distance = levenshtein(source, target)
    return float(distance) / max(len(source), len(target))


def levenshtein(source: str, target: str) -> int:
    """Computes the Levenshtein
    (https://en.wikipedia.org/wiki/Levenshtein_distance)
    and restricted Damerau-Levenshtein
    (https://en.wikipedia.org/wiki/Damerau%E2%80%93Levenshtein_distance)
    distances between two Unicode strings with given lengths using the
    Wagner-Fischer algorithm
    (https://en.wikipedia.org/wiki/Wagner%E2%80%93Fischer_algorithm).
    These distances are defined recursively, since the distance between two
    strings is just the cost of adjusting the last one or two characters plus
    the distance between the prefixes that exclude these characters (e.g. the
    distance between "tester" and "tested" is 1 + the distance between "teste"
    and "teste"). The Wagner-Fischer algorithm retains this idea but eliminates
    redundant computations by storing the distances between various prefixes in
    a matrix that is filled in iteratively.

    From jazzband/docopt-ng
    https://github.com/jazzband/docopt-ng/blob/bbed40a2335686d2e14ac0e6c3188374dc4784da/docopt.py
    """

    # Create matrix of correct size (this is s_len + 1 * t_len + 1 so that the
    # empty prefixes "" can also be included). The leftmost column represents
    # transforming various source prefixes into an empty string, which can
    # always be done by deleting all characters in the respective prefix, and
    # the top row represents transforming the empty string into various target
    # prefixes, which can always be done by inserting every character in the
    # respective prefix. The ternary used to build the list should ensure that
    # this row and column are now filled correctly
    s_range = range(len(source) + 1)
    t_range = range(len(target) + 1)
    matrix = [[(i if j == 0 else j) for j in t_range] for i in s_range]

    # Iterate through rest of matrix, filling it in with Levenshtein
    # distances for the remaining prefix combinations
    for i in s_range[1:]:
        for j in t_range[1:]:
            # Applies the recursive logic outlined above using the values
            # stored in the matrix so far. The options for the last pair of
            # characters are deletion, insertion, and substitution, which
            # amount to dropping the source character, the target character,
            # or both and then calculating the distance for the resulting
            # prefix combo. If the characters at this point are the same, the
            # situation can be thought of as a free substitution
            del_dist = matrix[i - 1][j] + 1
            ins_dist = matrix[i][j - 1] + 1
            sub_trans_cost = 0 if source[i - 1] == target[j - 1] else 1
            sub_dist = matrix[i - 1][j - 1] + sub_trans_cost

            # Choose option that produces smallest distance
            matrix[i][j] = min(del_dist, ins_dist, sub_dist)

    # At this point, the matrix is full, and the biggest prefixes are just the
    # strings themselves, so this is the desired distance
    return matrix[len(source)][len(target)]


def get_levenshtein_string(key: str, namespace: Dict[str, Any], threshold: float):
    """
    Generate an error message snippet for the first value in the provided namespace
    with the shortest normalized Levenshtein distance from the given key if that distance
    is below the threshold. Otherwise, return an empty string.

    As a heuristic, the threshold value is inversely correlated to the size of the namespace.
    For a small namespace (e.g. struct members), the threshold value can be the maximum of
    1.0 since the key must be one of the defined struct members. For a large namespace
    (e.g. types, builtin functions and state variables), the threshold value should be lower
    to ensure the matches are relevant.

    :param key: A string of the identifier being accessed
    :param namespace: A dictionary of the possible identifiers
    :param threshold: A floating value between 0.0 and 1.0

    :return: The error message snippet if the Levenshtein value is below the threshold,
        or an empty string.
    """
    distances = sorted([(i, levenshtein_norm(key, i)) for i in namespace], key=lambda k: k[1])
    if distances[0][1] <= threshold:
        return f" Did you mean '{distances[0][0]}?'"
    return ""


__all__ = [
    "cached_property",
]
