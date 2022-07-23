import binascii
import contextlib
import decimal
import functools
import sys
import time
import traceback
import warnings
from typing import List, Union

from vyper.exceptions import DecimalOverrideException, InvalidLiteral


class DecimalContextOverride(decimal.Context):
    def __setattr__(self, name, value):
        if name == "prec":
            if value < 78:
                # definitely don't want this to happen
                raise DecimalOverrideException("Overriding decimal precision disabled")
            elif value > 78:
                # not sure it's incorrect, might not be end of the world
                warnings.warn("Changing decimals precision could have unintended side effects!")
            # else: no-op, is ok

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


def signed_to_unsigned(int_, bits, strict=False):
    """
    Reinterpret a signed integer with n bits as an unsigned integer.
    The implementation is unforgiving in that it assumes the input is in
    bounds for int<bits>, in order to fail more loudly (and not hide
    errors in modular reasoning in consumers of this function).
    """
    if strict:
        lo, hi = int_bounds(signed=True, bits=bits)
        assert lo <= int_ <= hi
    if int_ < 0:
        return int_ + 2 ** bits
    return int_


def unsigned_to_signed(int_, bits, strict=False):
    """
    Reinterpret an unsigned integer with n bits as a signed integer.
    The implementation is unforgiving in that it assumes the input is in
    bounds for uint<bits>, in order to fail more loudly (and not hide
    errors in modular reasoning in consumers of this function).
    """
    if strict:
        lo, hi = int_bounds(signed=False, bits=bits)
        assert lo <= int_ <= hi
    if int_ > (2 ** (bits - 1)) - 1:
        return int_ - (2 ** bits)
    return int_


def is_power_of_two(n: int) -> bool:
    # busted for ints wider than 53 bits:
    # t = math.log(n, 2)
    # return math.ceil(t) == math.floor(t)
    return n != 0 and ((n & (n - 1)) == 0)


# https://stackoverflow.com/a/71122440/
def int_log2(n: int) -> int:
    return n.bit_length() - 1


# utility function for debugging purposes
def trace(n=5, out=sys.stderr):
    print("BEGIN TRACE", file=out)
    for x in list(traceback.format_stack())[-n:]:
        print(x.strip(), file=out)
    print("END TRACE", file=out)


# print a warning
def vyper_warn(msg, prefix="Warning: ", file_=sys.stderr):
    print(f"{prefix}{msg}", file=file_)


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
DECIMAL_EPSILON = decimal.Decimal(1) / DECIMAL_DIVISOR


def int_bounds(signed, bits):
    """
    calculate the bounds on an integer type
    ex. int_bounds(8, True) -> (-128, 127)
        int_bounds(8, False) -> (0, 255)
    """
    if signed:
        return -(2 ** (bits - 1)), (2 ** (bits - 1)) - 1
    return 0, (2 ** bits) - 1


# e.g. -1 -> -(2**256 - 1)
def evm_twos_complement(x: int) -> int:
    # return ((o + 2 ** 255) % 2 ** 256) - 2 ** 255
    return ((2 ** 256 - 1) ^ x) + 1


# EVM div semantics as a python function
def evm_div(x, y):
    if y == 0:
        return 0
    # NOTE: should be same as: round_towards_zero(Decimal(x)/Decimal(y))
    sign = -1 if (x * y) < 0 else 1
    return sign * (abs(x) // abs(y))  # adapted from py-evm


# EVM mod semantics as a python function
def evm_mod(x, y):
    if y == 0:
        return 0

    sign = -1 if x < 0 else 1
    return sign * (abs(x) % abs(y))  # adapted from py-evm


# EVM pow which wraps instead of hanging on "large" numbers
# (which can generated, for ex. in the unevaluated branch of the Shift builtin)
def evm_pow(x, y):
    assert x >= 0 and y >= 0
    return pow(x, y, 2 ** 256)


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
FUNCTION_WHITELIST = {"send"}

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
    "with",
    "label",
    "goto",
    "~extcode",
    "~selfcode",
    "~calldata",
    "~empty",
    "var_list",
}


EIP_170_LIMIT = 0x6000  # 24kb

SHA3_BASE = 30
SHA3_PER_WORD = 6


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


def timeit(func):
    @functools.wraps(func)
    def timeit_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        total_time = end_time - start_time
        print(f"Function {func.__name__} Took {total_time:.4f} seconds")
        return result

    return timeit_wrapper


@contextlib.contextmanager
def timer(msg):
    t0 = time.time()
    yield
    t1 = time.time()
    print(f"{msg} took {t1 - t0}s")


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


__all__ = ["cached_property"]
