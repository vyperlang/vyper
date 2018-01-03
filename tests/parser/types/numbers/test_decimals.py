def test_decimal_test(chain, check_gas, get_contract_with_gas_estimation):
    decimal_test = """
@public
def foo() -> num:
    return(floor(999.0))

@public
def fop() -> num:
    return(floor(333.0 + 666.0))

@public
def foq() -> num:
    return(floor(1332.1 - 333.1))

@public
def bar() -> num:
    return(floor(27.0 * 37.0))

@public
def baz() -> num:
    x = 27.0
    return(floor(x * 37.0))

@public
def baffle() -> num:
    return(floor(27.0 * 37))

@public
def mok() -> num:
    return(floor(999999.0 / 7.0 / 11.0 / 13.0))

@public
def mol() -> num:
    return(floor(499.5 / 0.5))

@public
def mom() -> num:
    return(floor(1498.5 / 1.5))

@public
def mon() -> num:
    return(floor(2997.0 / 3))

@public
def moo() -> num:
    return(floor(2997 / 3.0))

@public
def foom() -> num:
    return(floor(1999.0 % 1000.0))

@public
def foon() -> num:
    return(floor(1999.0 % 1000))

@public
def foop() -> num:
    return(floor(1999 % 1000.0))
    """

    c = get_contract_with_gas_estimation(decimal_test)
    pre_txs = len(chain.head_state.receipts)
    assert c.foo() == 999
    assert c.fop() == 999
    assert c.foq() == 999
    assert c.bar() == 999
    assert c.baz() == 999
    assert c.baffle() == 999
    assert c.mok() == 999
    assert c.mol() == 999
    assert c.mom() == 999
    assert c.mon() == 999
    assert c.moo() == 999
    assert c.foom() == 999
    assert c.foon() == 999
    assert c.foop() == 999
    post_txs = len(chain.head_state.receipts)

    print('Passed basic addition, subtraction and multiplication tests')
    check_gas(decimal_test, num_txs=(post_txs - pre_txs))


def test_harder_decimal_test(get_contract_with_gas_estimation):
    harder_decimal_test = """
@public
def phooey(inp: decimal) -> decimal:
    x = 10000.0
    for i in range(4):
        x = x * inp
    return x

@public
def arg(inp: decimal) -> decimal:
    return inp

@public
def garg() -> decimal:
    x = 4.5
    x *= 1.5
    return x

@public
def harg() -> decimal:
    x = 4.5
    x *= 2
    return x

@public
def iarg() -> wei_value:
    x = as_wei_value(7, wei)
    x *= 2
    return x
    """
    c = get_contract_with_gas_estimation(harder_decimal_test)
    assert c.phooey(1.2) == 20736.0
    assert c.phooey(-1.2) == 20736.0
    assert c.arg(-3.7) == -3.7
    assert c.arg(3.7) == 3.7
    assert c.garg() == 6.75
    assert c.harg() == 9.0
    assert c.iarg() == 14

    print('Passed fractional multiplication test')


def test_divide_minus_modulo(get_contract_with_gas_estimation):
    code = """
a: decimal
b: decimal

@public
def __init__():
    self.a = 10.19
    self.b = .1

@public
def decimal_literals() -> num:
    return 3.5 // .3

@public
def decimal_memory(x: decimal, y: decimal) -> num:
    return x // y

@public
def decimal_storage() -> num:
    return self.a // self.b

@public
def num_decimal_memory(x: num, y: decimal) -> num:
    return x // y

@public
def decimal_num_memory(x: decimal, y: num) -> num:
    return x // y
"""

    c = get_contract_with_gas_estimation(code)
    assert c.decimal_literals()  == 11
    assert c.decimal_memory(9, 3.5) == 2
    assert c.decimal_storage() == 101
    assert c.num_decimal_memory(10, 3.1) == 3
    assert c.decimal_num_memory(7.5, 2) == 3
