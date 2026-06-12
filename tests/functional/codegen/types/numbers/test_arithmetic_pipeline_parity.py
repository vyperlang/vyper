"""
Differential tests for safe/unsafe arithmetic: for every operation and a
boundary-rich operand set, the legacy pipeline, the venom pipeline, and an
exact Python oracle must all agree (same value, or revert in both).

Compiles bytecode-only under each pipeline explicitly, so this is immune
to the output-format masking where legacy codegen runs (and validates)
even under --experimental-codegen.
"""

import itertools
import math

import pytest

from tests.evm_backends.base_env import EvmError
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.semantics.types import DecimalT, IntegerT
from vyper.utils import evm_div, evm_mod

REVERT = object()

INT_WIDTHS = [8, 16, 64, 128, 136, 160, 248, 256]
INT_TYPES = [IntegerT(s, w) for w in INT_WIDTHS for s in (True, False)]

# exponent/base literals baked into the per-type contract
POW_EXPS = [2, 3, 7]
POW_BASES = [2, 7]
POW_NEG_BASES = [-2]


def _boundary_values(typ):
    lo, hi = typ.int_bounds
    vals = {lo, lo + 1, 0, 1, 2, 3, 7, hi - 1, hi, hi // 2, hi // 2 + 1}
    s = math.isqrt(hi)
    vals |= {s, s + 1}
    if typ.is_signed:
        vals |= {-1, -2, -3, -7, -s, -s - 1, lo // 2, lo // 2 - 1}
    if isinstance(typ, DecimalT):
        d = typ.divisor
        vals |= {d, -d, 7 * d, -7 * d, lo + d, hi - d}
    return sorted(v for v in vals if lo <= v <= hi)


def _wrap(val, typ):
    # two's complement wrap to typ's bit width (for unsafe_* ops)
    m = val % (1 << typ.bits)
    if typ.is_signed and m >= 1 << (typ.bits - 1):
        m -= 1 << typ.bits
    return m


def _checked(res, typ):
    lo, hi = typ.int_bounds
    return res if lo <= res <= hi else REVERT


def safe_oracle(op, x, y, typ):
    divisor = typ.divisor if isinstance(typ, DecimalT) else 1
    if op == "+":
        return _checked(x + y, typ)
    if op == "-":
        return _checked(x - y, typ)
    if op == "*":
        # decimal: truncating divide the raw product by the divisor
        return _checked(evm_div(x * y, divisor), typ)
    if op == "/":  # decimal division
        if y == 0:
            return REVERT
        return _checked(evm_div(x * divisor, y), typ)
    if op == "//":
        if y == 0:
            return REVERT
        return _checked(evm_div(x, y), typ)
    if op == "%":
        if y == 0:
            return REVERT
        return _checked(evm_mod(x, y), typ)
    raise AssertionError(op)


def pow_oracle(base, exp, typ):
    if exp < 0 or (base < 0 and exp < 0):
        return REVERT
    return _checked(base**exp, typ)


def unsafe_oracle(op, x, y, typ):
    if op == "div":
        return _wrap(evm_div(x, y), typ)
    res = {"add": x + y, "sub": x - y, "mul": x * y}[op]
    return _wrap(res, typ)


def _source(typ):
    funcs = []
    for name, op in [("add", "+"), ("sub", "-"), ("mul", "*"), ("floordiv", "//"), ("mod", "%")]:
        if isinstance(typ, DecimalT) and op == "//":
            name, op = ("div", "/")
        funcs.append(f"""
@external
def safe_{name}(x: {typ}, y: {typ}) -> {typ}:
    return x {op} y
""")
    if typ.is_signed:
        funcs.append(f"""
@external
def neg(x: {typ}) -> {typ}:
    return -x
""")
    if isinstance(typ, IntegerT):
        for op in ("add", "sub", "mul", "div"):
            funcs.append(f"""
@external
def unsafe_{op}_(x: {typ}, y: {typ}) -> {typ}:
    return unsafe_{op}(x, y)
""")
        for e in POW_EXPS:
            funcs.append(f"""
@external
def pow_exp{e}(x: {typ}) -> {typ}:
    return x ** {e}
""")
        bases = POW_BASES + (POW_NEG_BASES if typ.is_signed else [])
        for b in bases:
            name = f"m{-b}" if b < 0 else str(b)
            funcs.append(f"""
@external
def pow_base{name}(y: {typ}) -> {typ}:
    return ({b}) ** y
""")
    return "\n".join(funcs)


def _deploy_both(env, typ):
    src = _source(typ)
    out = compile_code(
        src,
        output_formats=("bytecode", "abi"),
        settings=Settings(experimental_codegen=False, enable_decimals=True),
    )
    abi, legacy_bytecode = out["abi"], out["bytecode"]
    venom_bytecode = compile_code(
        src,
        output_formats=("bytecode",),
        settings=Settings(experimental_codegen=True, enable_decimals=True),
    )["bytecode"]
    legacy = env.deploy(abi, bytes.fromhex(legacy_bytecode.removeprefix("0x")))
    venom = env.deploy(abi, bytes.fromhex(venom_bytecode.removeprefix("0x")))
    return legacy, venom


def _call(contract, fn, *args):
    try:
        return getattr(contract, fn)(*args)
    except EvmError:
        return REVERT


def _check(legacy, venom, fn, expected, *args):
    actual_legacy = _call(legacy, fn, *args)
    actual_venom = _call(venom, fn, *args)
    ok_l = actual_legacy is REVERT if expected is REVERT else actual_legacy == expected
    ok_v = actual_venom is REVERT if expected is REVERT else actual_venom == expected
    assert ok_l and ok_v, (
        f"{fn}{args}: oracle={'REVERT' if expected is REVERT else expected} "
        f"legacy={'REVERT' if actual_legacy is REVERT else actual_legacy} "
        f"venom={'REVERT' if actual_venom is REVERT else actual_venom}"
    )


@pytest.mark.parametrize("typ", INT_TYPES + [DecimalT()], ids=str)
def test_binop_parity(env, typ):
    legacy, venom = _deploy_both(env, typ)
    vals = _boundary_values(typ)

    ops = [("add", "+"), ("sub", "-"), ("mul", "*"), ("mod", "%")]
    ops += [("div", "/")] if isinstance(typ, DecimalT) else [("floordiv", "//")]

    for x, y in itertools.product(vals, vals):
        for name, op in ops:
            _check(legacy, venom, f"safe_{name}", safe_oracle(op, x, y, typ), x, y)

    if typ.is_signed:
        lo, hi = typ.int_bounds
        for x in vals:
            expected = REVERT if x == lo else -x
            _check(legacy, venom, "neg", expected, x)


@pytest.mark.parametrize("typ", INT_TYPES, ids=str)
def test_unsafe_parity(env, typ):
    legacy, venom = _deploy_both(env, typ)
    vals = _boundary_values(typ)

    for x, y in itertools.product(vals, vals):
        for op in ("add", "sub", "mul", "div"):
            _check(legacy, venom, f"unsafe_{op}_", unsafe_oracle(op, x, y, typ), x, y)


@pytest.mark.parametrize("typ", INT_TYPES, ids=str)
def test_pow_parity(env, typ):
    from vyper.codegen.arithmetic import calculate_largest_base, calculate_largest_power

    legacy, venom = _deploy_both(env, typ)
    lo, hi = typ.int_bounds

    # literal exponent: probe the base bounds
    for e in POW_EXPS:
        b_lo, b_hi = calculate_largest_base(e, typ.bits, typ.is_signed)
        probes = {b_lo - 1, b_lo, b_lo + 1, b_hi - 1, b_hi, b_hi + 1, 0, 1, 2}
        if typ.is_signed:
            probes |= {-1, -2}
        for x in sorted(p for p in probes if lo <= p <= hi):
            _check(legacy, venom, f"pow_exp{e}", pow_oracle(x, e, typ), x)

    # literal base: probe the exponent bounds
    bases = POW_BASES + (POW_NEG_BASES if typ.is_signed else [])
    for base in bases:
        name = f"m{-base}" if base < 0 else str(base)
        e_hi = calculate_largest_power(base, typ.bits, typ.is_signed)
        probes = {0, 1, 2, e_hi - 1, e_hi, e_hi + 1}
        if typ.is_signed:
            probes |= {-1, lo}
        for y in sorted(p for p in probes if lo <= p <= hi):
            _check(legacy, venom, f"pow_base{name}", pow_oracle(base, y, typ), y)


def _deploy_both_src(env, src):
    out = compile_code(
        src,
        output_formats=("bytecode", "abi"),
        settings=Settings(experimental_codegen=False, enable_decimals=True),
    )
    abi, legacy_bytecode = out["abi"], out["bytecode"]
    venom_bytecode = compile_code(
        src,
        output_formats=("bytecode",),
        settings=Settings(experimental_codegen=True, enable_decimals=True),
    )["bytecode"]
    legacy = env.deploy(abi, bytes.fromhex(legacy_bytecode.removeprefix("0x")))
    venom = env.deploy(abi, bytes.fromhex(venom_bytecode.removeprefix("0x")))
    return legacy, venom


def test_math_isqrt_parity(env):
    src = """
import math

@external
def f(x: uint256) -> uint256:
    return math.isqrt(x)
    """
    legacy, venom = _deploy_both_src(env, src)

    probes = {0, 1, 2, 3, 4, 5, 2**256 - 1}
    for root in (2, 10**18, 2**100, 2**128 - 1):
        sq = root * root
        probes |= {sq - 1, sq, sq + 1}
    for x in sorted(probes):
        expected = math.isqrt(x)
        _check(legacy, venom, "f", expected, x)


def test_math_sqrt_parity(env):
    # decimal sqrt is an iterative approximation; the spec is "whatever
    # legacy computes" -- require bit-identical results from venom
    src = """
import math

@external
def f(x: decimal) -> decimal:
    return math.sqrt(x)
    """
    legacy, venom = _deploy_both_src(env, src)

    d = DecimalT().divisor
    _, hi = DecimalT().int_bounds
    probes = [0, 1, d // 2, d, 2 * d, 4 * d, 4 * d - 1, 4 * d + 1, 10**18, hi // d, hi // 2, hi]
    for x in probes:
        left = _call(legacy, "f", x)
        right = _call(venom, "f", x)
        assert left == right, f"sqrt({x}): legacy={left} venom={right}"


def test_uint2str_parity(env):
    funcs = []
    for bits in (8, 64, 256):
        funcs.append(f"""
@external
def f{bits}(x: uint{bits}) -> String[78]:
    return uint2str(x)
""")
    legacy, venom = _deploy_both_src(env, "\n".join(funcs))

    for bits in (8, 64, 256):
        hi = (1 << bits) - 1
        probes = {0, 1, 9, 10, 11, 99, 100, hi - 1, hi}
        for x in sorted(probes):
            _check(legacy, venom, f"f{bits}", str(x), x)


def test_shift_op_parity(env):
    src = """
@external
def shl_u(x: uint256, n: uint256) -> uint256:
    return x << n

@external
def shr_u(x: uint256, n: uint256) -> uint256:
    return x >> n

@external
def shl_s(x: int256, n: uint256) -> int256:
    return x << n

@external
def sar_s(x: int256, n: uint256) -> int256:
    return x >> n
    """
    legacy, venom = _deploy_both_src(env, src)

    def sar(x, n):
        return x >> n if n < 256 else (-1 if x < 0 else 0)

    def wrap256(v):
        m = v % (1 << 256)
        return m - (1 << 256) if m >= 1 << 255 else m

    xs_u = [0, 1, 7, 2**255, 2**256 - 1]
    xs_s = [0, 1, 7, -1, -7, -(2**255), 2**255 - 1]
    ns = [0, 1, 8, 255, 256, 257, 2**256 - 1]

    for n in ns:
        for x in xs_u:
            _check(legacy, venom, "shl_u", (x << n) % 2**256 if n < 256 else 0, x, n)
            _check(legacy, venom, "shr_u", x >> n if n < 256 else 0, x, n)
        for x in xs_s:
            _check(legacy, venom, "shl_s", wrap256(x << n) if n < 256 else 0, x, n)
            _check(legacy, venom, "sar_s", sar(x, n), x, n)


def test_floor_ceil_parity(env):
    src = """
@external
def floor_(x: decimal) -> int256:
    return floor(x)

@external
def ceil_(x: decimal) -> int256:
    return ceil(x)
    """
    legacy, venom = _deploy_both_src(env, src)

    d = DecimalT().divisor
    lo, hi = DecimalT().int_bounds
    probes = {0, 1, d - 1, d, d + 1, 3 * d // 2, 2 * d, -1, -d + 1, -d, -d - 1, -3 * d // 2}
    probes |= {lo, lo + 1, hi, hi - 1}

    for x in sorted(probes):
        # floor/ceil on the raw fixed-point representation
        _check(legacy, venom, "floor_", x // d, x)
        _check(legacy, venom, "ceil_", -((-x) // d), x)
