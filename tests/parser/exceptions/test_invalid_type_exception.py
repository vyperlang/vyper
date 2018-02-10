import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidTypeException

fail_list = [
    """
x: bat
    """,
    """
x: 5
    """,
    """
x: num[int]
    """,
    """
x: num[-1]
    """,
    """
x: num[3.5]
    """,
    """
x: {num[5]: num[7]}
    """,
    """
x: [bar, baz]
    """,
    """
x: [bar(num), baz(baffle)]
    """,
    """
x: {bar: num, decimal: num}
    """,
    """
x: {bar: num, 5: num}
    """,
    """
def foo(x): pass
    """,
    """
b: {num: num, address: address}
    """,
    """
b: {num: num, address: address}
    """,
    """
b: num[num, decimal]
    """,
    """
b: num[num: address]
    """,
    """
x: num[address[bool]]
@public
def foo() -> num(wei / sec):
    pass
    """,
    """
@public
def foo() -> {cow: num, dog: num}:
    return {cow: 5, dog: 7}
    """,
    """
x: wei(wei)
    """,
    """
x: num(address)
    """,
    """
x: num(wei and sec)
    """,
    """
x: num(2 ** 2)
    """,
    """
x: num(wei ** -1)
    """,
    """
x: num(wei >> 3)
    """,
    """
x: num()
    """,
    """
x: bytes <= wei
    """,
    """
x: string <= 33
    """,
    """
x: 1 <= bytes <= 3
    """,
    """
x: bytes <= 33.3
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with raises(InvalidTypeException):
        compiler.compile(bad_code)
