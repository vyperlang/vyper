from decimal import Decimal


def test_decimal_test(get_contract_with_gas_estimation):
    decimal_test = """
@public
def foo() -> int128:
    return(floor(999.0))

@public
def fop() -> int128:
    return(floor(333.0 + 666.0))

@public
def foq() -> int128:
    return(floor(1332.1 - 333.1))

@public
def bar() -> int128:
    return(floor(27.0 * 37.0))

@public
def baz() -> int128:
    x: decimal = 27.0
    return(floor(x * 37.0))

@public
def mok() -> int128:
    return(floor(999999.0 / 7.0 / 11.0 / 13.0))

@public
def mol() -> int128:
    return(floor(499.5 / 0.5))

@public
def mom() -> int128:
    return(floor(1498.5 / 1.5))

@public
def moo() -> int128:
    return(floor(2997.0 / 3.0))

@public
def foom() -> int128:
    return(floor(1999.0 % 1000.0))

@public
def foop() -> int128:
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

    print('Passed basic addition, subtraction and multiplication tests')


def test_harder_decimal_test(get_contract_with_gas_estimation):
    harder_decimal_test = """
@public
def phooey(inp: decimal) -> decimal:
    x: decimal = 10000.0
    for i in range(4):
        x = x * inp
    return x

@public
def arg(inp: decimal) -> decimal:
    return inp

@public
def garg() -> decimal:
    x: decimal = 4.5
    x *= 1.5
    return x

@public
def harg() -> decimal:
    x: decimal = 4.5
    x *= 2.0
    return x

@public
def iarg() -> wei_value:
    x: wei_value = as_wei_value(7, "wei")
    x *= 2
    return x
    """

    c = get_contract_with_gas_estimation(harder_decimal_test)
    assert c.phooey(Decimal('1.2')) == Decimal('20736.0')
    assert c.phooey(Decimal('-1.2')) == Decimal('20736.0')
    assert c.arg(Decimal('-3.7')) == Decimal('-3.7')
    assert c.arg(Decimal('3.7')) == Decimal('3.7')
    assert c.garg() == Decimal('6.75')
    assert c.harg() == Decimal('9.0')
    assert c.iarg() == Decimal('14')

    print('Passed fractional multiplication test')


def test_mul_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    mul_code = """

@public
def _num_mul(x: decimal, y: decimal) -> decimal:
    return x * y

    """

    c = get_contract_with_gas_estimation(mul_code)

    NUM_1 = Decimal('85070591730234615865843651857942052864')
    NUM_2 = Decimal('136112946768375385385349842973')

    assert_tx_failed(lambda: c._num_mul(NUM_1, NUM_2))


def test_decimal_min_max_literals(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def maximum():
    a: decimal = 170141183460469231731687303715884105726.
@public
def minimum():
    a: decimal = -170141183460469231731687303715884105726.
    """
    c = get_contract_with_gas_estimation(code)

    assert c.maximum() == []
    assert c.minimum() == []
