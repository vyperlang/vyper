import warnings
from decimal import ROUND_DOWN, Decimal, getcontext

import pytest

from vyper import compile_code
from vyper.exceptions import (
    DecimalOverrideException,
    InvalidOperation,
    OverflowException,
    TypeMismatch,
)
from vyper.utils import DECIMAL_EPSILON, SizeLimits


def test_decimal_override():
    getcontext().prec = 78  # setting prec to 78 is ok

    # consumers of vyper, even as a library, are not allowed to reduce Decimal precision
    with pytest.raises(DecimalOverrideException):
        getcontext().prec = 77

    with warnings.catch_warnings(record=True) as w:
        getcontext().prec = 79
        # check warnings were issued
        assert len(w) == 1
        assert (
            str(w[-1].message) == "Changing decimals precision could have unintended side effects!"
        )


@pytest.mark.parametrize("op", ["//", "**", "&", "|", "^"])
def test_invalid_ops(op):
    code = f"""
@external
def foo(x: decimal, y: decimal) -> decimal:
    return x {op} y
    """
    with pytest.raises(InvalidOperation):
        compile_code(code)


@pytest.mark.parametrize("op", ["not"])
def test_invalid_unary_ops(op):
    code = f"""
@external
def foo(x: decimal) -> decimal:
    return {op} x
    """
    with pytest.raises(InvalidOperation):
        compile_code(code)


def quantize(x: Decimal) -> Decimal:
    return x.quantize(DECIMAL_EPSILON, rounding=ROUND_DOWN)


def test_decimal_test(get_contract_with_gas_estimation):
    decimal_test = """
@external
def foo() -> int256:
    return(floor(999.0))

@external
def fop() -> int256:
    return(floor(333.0 + 666.0))

@external
def foq() -> int256:
    return(floor(1332.1 - 333.1))

@external
def bar() -> int256:
    return(floor(27.0 * 37.0))

@external
def baz() -> int256:
    x: decimal = 27.0
    return(floor(x * 37.0))

@external
def mok() -> int256:
    return(floor(999999.0 / 7.0 / 11.0 / 13.0))

@external
def mol() -> int256:
    return(floor(499.5 / 0.5))

@external
def mom() -> int256:
    return(floor(1498.5 / 1.5))

@external
def moo() -> int256:
    return(floor(2997.0 / 3.0))

@external
def foom() -> int256:
    return(floor(1999.0 % 1000.0))

@external
def foop() -> int256:
    return(floor(1999.0 % 1000.0))
    """

    c = get_contract_with_gas_estimation(decimal_test)

    assert c.foo() == 999
    assert c.fop() == 999
    assert c.foq() == 999
    assert c.bar() == 999
    assert c.baz() == 999
    assert c.mok() == 999
    assert c.mol() == 999
    assert c.mom() == 999
    assert c.moo() == 999
    assert c.foom() == 999
    assert c.foop() == 999

    print("Passed basic addition, subtraction and multiplication tests")


def test_harder_decimal_test(get_contract_with_gas_estimation):
    harder_decimal_test = """
@external
def phooey(inp: decimal) -> decimal:
    x: decimal = 10000.0
    for i: uint256 in range(4):
        x = x * inp
    return x

@external
def arg(inp: decimal) -> decimal:
    return inp

@external
def garg() -> decimal:
    x: decimal = 4.5
    x *= 1.5
    return x

@external
def harg() -> decimal:
    x: decimal = 4.5
    x *= 2.0
    return x

@external
def iarg() -> uint256:
    x: uint256 = as_wei_value(7, "wei")
    x *= 2
    return x
    """

    c = get_contract_with_gas_estimation(harder_decimal_test)
    assert c.phooey(Decimal("1.2")) == Decimal("20736.0")
    assert c.phooey(Decimal("-1.2")) == Decimal("20736.0")
    assert c.arg(Decimal("-3.7")) == Decimal("-3.7")
    assert c.arg(Decimal("3.7")) == Decimal("3.7")
    assert c.garg() == Decimal("6.75")
    assert c.harg() == Decimal("9.0")
    assert c.iarg() == Decimal("14")

    print("Passed fractional multiplication test")


def test_mul_overflow(tx_failed, get_contract_with_gas_estimation):
    mul_code = """

@external
def _num_mul(x: decimal, y: decimal) -> decimal:
    return x * y

    """

    c = get_contract_with_gas_estimation(mul_code)

    x = Decimal("85070591730234615865843651857942052864")
    y = Decimal("136112946768375385385349842973")

    with tx_failed():
        c._num_mul(x, y)

    x = SizeLimits.MAX_AST_DECIMAL
    y = 1 + DECIMAL_EPSILON

    with tx_failed():
        c._num_mul(x, y)

    assert c._num_mul(x, Decimal(1)) == x

    assert c._num_mul(x, 1 - DECIMAL_EPSILON) == quantize(x * (1 - DECIMAL_EPSILON))

    x = SizeLimits.MIN_AST_DECIMAL
    assert c._num_mul(x, 1 - DECIMAL_EPSILON) == quantize(x * (1 - DECIMAL_EPSILON))


# division failure modes(!)
def test_div_overflow(get_contract, tx_failed):
    code = """
@external
def foo(x: decimal, y: decimal) -> decimal:
    return x / y
    """

    c = get_contract(code)

    x = SizeLimits.MIN_AST_DECIMAL
    y = -DECIMAL_EPSILON

    with tx_failed():
        c.foo(x, y)
    with tx_failed():
        c.foo(x, Decimal(0))
    with tx_failed():
        c.foo(y, Decimal(0))

    y = Decimal(1) - DECIMAL_EPSILON  # 0.999999999
    with tx_failed():
        c.foo(x, y)

    y = Decimal(-1)
    with tx_failed():
        c.foo(x, y)

    assert c.foo(x, Decimal(1)) == x
    assert c.foo(x, 1 + DECIMAL_EPSILON) == quantize(x / (1 + DECIMAL_EPSILON))

    x = SizeLimits.MAX_AST_DECIMAL

    with tx_failed():
        c.foo(x, DECIMAL_EPSILON)

    y = Decimal(1) - DECIMAL_EPSILON
    with tx_failed():
        c.foo(x, y)

    assert c.foo(x, Decimal(1)) == x

    assert c.foo(x, 1 + DECIMAL_EPSILON) == quantize(x / (1 + DECIMAL_EPSILON))


def test_decimal_min_max_literals(tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def maximum():
    a: decimal = 18707220957835557353007165858768422651595.9365500927
@external
def minimum():
    a: decimal = -18707220957835557353007165858768422651595.9365500928
    """
    c = get_contract_with_gas_estimation(code)

    assert c.maximum() == []
    assert c.minimum() == []


def test_scientific_notation(get_contract_with_gas_estimation):
    code = """
@external
def foo() -> decimal:
    return 1e-10

@external
def bar(num: decimal) -> decimal:
    return num + -1e38
    """
    c = get_contract_with_gas_estimation(code)

    assert c.foo() == Decimal("1e-10")  # Smallest possible decimal
    assert c.bar(Decimal("1e37")) == Decimal("-9e37")  # Math lines up


def test_exponents():
    code = """
@external
def foo() -> decimal:
    return 2.2 ** 2.0
    """

    with pytest.raises(TypeMismatch):
        compile_code(code)


def test_decimal_nested_intermediate_overflow():
    code = """
@external
def foo():
    a: decimal = 18707220957835557353007165858768422651595.9365500927 + 1e-10 - 1e-10
    """
    with pytest.raises(OverflowException):
        compile_code(code)


def test_replace_decimal_nested_intermediate_underflow(dummy_input_bundle):
    code = """
@external
def foo():
    a: decimal = -18707220957835557353007165858768422651595.9365500928 - 1e-10 + 1e-10
    """
    with pytest.raises(OverflowException):
        compile_code(code)


def test_invalid_floordiv():
    code = """
@external
def foo():
    a: decimal = 5.0 // 9.0
    """
    with pytest.raises(InvalidOperation) as e:
        compile_code(code)

    assert e.value._hint == "did you mean `5.0 / 9.0`?"
