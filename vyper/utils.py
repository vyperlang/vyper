import binascii
import functools
import sys
import traceback
from typing import Dict, List, Union

from vyper.exceptions import InvalidLiteral

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


# Encodes an address using ethereum's checksum scheme
def checksum_encode(addr):  # Expects an input of the form 0x<40 hex chars>
    assert addr[:2] == "0x" and len(addr) == 42
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


# memory used for system purposes, not for variables
class MemoryPositions:
    MAXDECIMAL = 32
    MINDECIMAL = 64
    FREE_VAR_SPACE = 128
    FREE_VAR_SPACE2 = 160
    FREE_LOOP_INDEX = 192
    RESERVED_MEMORY = 224


# Sizes of different data types. Used to clamp types.
class SizeLimits:
    ADDRSIZE = 2 ** 160
    MAX_INT128 = 2 ** 127 - 1
    MIN_INT128 = -(2 ** 127)
    MAX_INT256 = 2 ** 255 - 1
    MIN_INT256 = -(2 ** 255)
    MAXDECIMAL = (2 ** 127 - 1) * DECIMAL_DIVISOR
    MINDECIMAL = (-(2 ** 127)) * DECIMAL_DIVISOR
    MAX_UINT8 = 2 ** 8 - 1
    MAX_UINT256 = 2 ** 256 - 1

    @classmethod
    def in_bounds(cls, type_str, value):
        assert isinstance(type_str, str)
        if type_str == "decimal":
            return float(cls.MINDECIMAL) <= value <= float(cls.MAXDECIMAL)
        if type_str == "uint8":
            return 0 <= value <= cls.MAX_UINT8
        elif type_str == "uint256":
            return 0 <= value <= cls.MAX_UINT256
        elif type_str == "int128":
            return cls.MIN_INT128 <= value <= cls.MAX_INT128
        elif type_str == "int256":
            return cls.MIN_INT256 <= value <= cls.MAX_INT256
        else:
            raise Exception(f'Unknown type "{type_str}" supplied.')


# Map representing all limits loaded into a contract as part of the initializer
# code.
LOADED_LIMITS: Dict[int, int] = {
    MemoryPositions.MAXDECIMAL: SizeLimits.MAXDECIMAL,
    MemoryPositions.MINDECIMAL: SizeLimits.MINDECIMAL,
}


# Otherwise reserved words that are whitelisted for function declarations
FUNCTION_WHITELIST = {
    "send",
}

# List of valid LLL macros.
VALID_LLL_MACROS = {
    "assert",
    "break",
    "ceil32",
    "clamp",
    "clamp",
    "clamp_nonzero",
    "clampge",
    "clampgt",
    "clample",
    "clamplt",
    "codeload",
    "continue",
    "debugger",
    "ge",
    "if",
    "le",
    "lll",
    "ne",
    "pass",
    "repeat",
    "seq",
    "set",
    "sge",
    "sha3_32",
    "sha3_64",
    "sle",
    "uclampge",
    "uclampgt",
    "uclample",
    "uclamplt",
    "with",
    "~codelen",
    "label",
    "goto",
}

# Available base types
BASE_TYPES = {"int128", "int256", "decimal", "bytes32", "uint8", "uint256", "bool", "address"}


def is_instances(instances, instance_type):
    return all([isinstance(inst, instance_type) for inst in instances])


def iterable_cast(cast_type):
    def yf(func):
        @functools.wraps(func)
        def f(*args, **kwargs):
            return cast_type(func(*args, **kwargs))

        return f

    return yf


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


__all__ = [
    "cached_property",
]
