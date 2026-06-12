"""
Differential tests: the legacy and venom pipelines must agree on which
`convert()` programs are valid, and on the runtime clamp behavior at the
boundaries of every numeric conversion.

Note these tests compile bytecode-only, on purpose: several output
formats (ir_dict, metadata, abi) run the *legacy* codegen even under
`--experimental-codegen`, so multi-format compilation (as used by most
fixtures) lets legacy validation mask venom accepts-invalid bugs.
"""

import itertools

import pytest

from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.exceptions import VyperException
from vyper.semantics.types import DecimalT, IntegerT
from vyper.utils import evm_div

INT_TYPES = ["uint8", "int8", "uint128", "int128", "uint160", "uint256", "int256"]
BYTES_M_TYPES = ["bytes1", "bytes4", "bytes20", "bytes21", "bytes32"]
SCALAR_TYPES = ["decimal", "bool", "address"]
BYTESTRING_TYPES = ["Bytes[20]", "Bytes[32]", "Bytes[33]", "String[20]", "String[32]", "String[33]"]
FLAG_TYPES = ["Roles"]

ALL_TYPES = INT_TYPES + BYTES_M_TYPES + SCALAR_TYPES + BYTESTRING_TYPES + FLAG_TYPES

FLAG_PREAMBLE = """
flag Roles:
    ADMIN
    USER
    GUEST
"""


def _make_code(i_typ, o_typ):
    preamble = FLAG_PREAMBLE if "Roles" in (i_typ, o_typ) else ""
    return f"""{preamble}
@external
def foo(x: {i_typ}) -> {o_typ}:
    return convert(x, {o_typ})
    """


def _compile_verdict(code, use_venom):
    settings = Settings(experimental_codegen=use_venom, enable_decimals=True)
    try:
        compile_code(code, output_formats=("bytecode",), settings=settings)
        return "accept"
    except VyperException as e:
        return type(e).__name__


@pytest.mark.parametrize(
    "i_typ,o_typ", [(i, o) for i, o in itertools.product(ALL_TYPES, ALL_TYPES) if i != o]
)
def test_convert_acceptance_parity(i_typ, o_typ):
    """
    Both pipelines accept the same convert() programs and reject with the
    same exception type.
    """
    code = _make_code(i_typ, o_typ)
    legacy = _compile_verdict(code, use_venom=False)
    venom = _compile_verdict(code, use_venom=True)
    assert legacy == venom, f"{i_typ} -> {o_typ}: legacy={legacy} venom={venom}"


def _parse_int(name):
    return IntegerT(name.startswith("i"), int(name.replace("uint", "").replace("int", "")))


def _conversion_window(i_typ, o_typ):
    """
    The legal input window for convert(x, o_typ), in x's raw representation,
    plus a function mapping an in-window raw input to the expected raw output.
    """
    if isinstance(i_typ, IntegerT) and isinstance(o_typ, DecimalT):
        in_lo, in_hi = i_typ.int_bounds
        out_lo, out_hi = o_typ.int_bounds
        divisor = o_typ.divisor
        lo = max(in_lo, evm_div(out_lo, divisor))
        hi = min(in_hi, evm_div(out_hi, divisor))
        return lo, hi, lambda x: x * divisor

    if isinstance(i_typ, DecimalT) and isinstance(o_typ, IntegerT):
        in_lo, in_hi = i_typ.int_bounds
        out_lo, out_hi = o_typ.int_bounds
        divisor = i_typ.divisor
        lo = max(in_lo, out_lo * divisor)
        hi = min(in_hi, out_hi * divisor)
        return lo, hi, lambda x: evm_div(x, divisor)

    assert isinstance(i_typ, IntegerT) and isinstance(o_typ, IntegerT)
    in_lo, in_hi = i_typ.int_bounds
    out_lo, out_hi = o_typ.int_bounds
    return max(in_lo, out_lo), min(in_hi, out_hi), lambda x: x


NUMERIC_PAIRS = [
    ("int256", "decimal"),
    ("uint256", "decimal"),
    ("int128", "decimal"),
    ("decimal", "int256"),
    ("decimal", "uint256"),
    ("decimal", "int8"),
    ("decimal", "uint8"),
    ("int256", "uint8"),
    ("int256", "int8"),
    ("int256", "uint256"),
    ("uint256", "int256"),
    ("uint256", "uint8"),
    ("int8", "int256"),
    ("int8", "uint256"),
]


@pytest.mark.parametrize("i_name,o_name", NUMERIC_PAIRS)
def test_numeric_convert_boundaries(get_contract, tx_failed, i_name, o_name):
    """
    Exact behavior at the edges of the legal input window: the boundary
    values convert to the expected result, one past them reverts.

    Runs under whichever pipeline the session selects, so CI exercises
    both. Regression test for GH 5110 (int->decimal lower bound off by
    one under venom).
    """

    def parse(name):
        return DecimalT() if name == "decimal" else _parse_int(name)

    i_typ, o_typ = parse(i_name), parse(o_name)

    code = f"""
@external
def foo(x: {i_name}) -> {o_name}:
    return convert(x, {o_name})
    """
    c = get_contract(code)

    lo, hi, expected = _conversion_window(i_typ, o_typ)
    in_lo, in_hi = i_typ.int_bounds

    assert c.foo(lo) == expected(lo)
    assert c.foo(hi) == expected(hi)

    # one past each boundary must revert, when representable in the input type
    if lo - 1 >= in_lo:
        with tx_failed():
            c.foo(lo - 1)
    if hi + 1 <= in_hi:
        with tx_failed():
            c.foo(hi + 1)
