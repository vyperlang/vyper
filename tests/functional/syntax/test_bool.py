import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidOperation, SyntaxException, TypeMismatch

fail_list = [
    """
@external
def foo():
    x: bool = True
    x = 5
    """,
    (
        """
@external
def foo():
    True = 3
    """,
        SyntaxException,
    ),
    """
@external
def foo():
    x: bool = True
    x = 129
    """,
    (
        """
@external
def foo() -> bool:
    return (1 == 2) <= (1 == 1)
    """,
        InvalidOperation,
    ),
    """
@external
def foo() -> bool:
    return (1 == 2) or 3
    """,
    """
@external
def foo() -> bool:
    return 1.0 == 1
    """,
    """
@external
def foo() -> bool:
    a: address = empty(address)
    return a == 1
    """,
    (
        """
@external
def foo(a: address) -> bool:
    return not a
    """,
        InvalidOperation,
    ),
    """
@external
def test(a: address) -> bool:
    assert(a)
    return True
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_bool_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    x: bool = True
    z: bool = x and False
    """,
    """
@external
def foo():
    x: bool = True
    z: bool = x and False
    """,
    """
@external
def foo():
    x: bool = True
    x = False
    """,
    """
@external
def foo() -> bool:
    return 1 == 1
    """,
    """
@external
def foo() -> bool:
    return 1 != 1
    """,
    """
@external
def foo() -> bool:
    return 1 > 1
    """,
    """
@external
def foo() -> bool:
    return 2 >= 1
    """,
    """
@external
def foo() -> bool:
    return 1 < 1
    """,
    """
@external
def foo() -> bool:
    return 1 <= 1
    """,
    """
@external
def foo2(a: address) -> bool:
    return a != empty(address)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_bool_success(good_code):
    assert compiler.compile_code(good_code) is not None


@pytest.mark.parametrize(
    "length,value,result",
    [
        (1, "a", False),
        (1, "", True),
        (8, "helloooo", False),
        (8, "hello", False),
        (8, "", True),
        (40, "a", False),
        (40, "hellohellohellohellohellohellohellohello", False),
        (40, "", True),
    ],
)
@pytest.mark.parametrize("op", ["==", "!="])
def test_empty_string_comparison(get_contract_with_gas_estimation, length, value, result, op):
    contract = f"""
@external
def foo(xs: String[{length}]) -> bool:
    return xs {op} ""
    """
    c = get_contract_with_gas_estimation(contract)
    if op == "==":
        assert c.foo(value) == result
    elif op == "!=":
        assert c.foo(value) != result


@pytest.mark.parametrize(
    "length,value,result",
    [
        (1, b"a", False),
        (1, b"", True),
        (8, b"helloooo", False),
        (8, b"hello", False),
        (8, b"", True),
        (40, b"a", False),
        (40, b"hellohellohellohellohellohellohellohello", False),
        (40, b"", True),
    ],
)
@pytest.mark.parametrize("op", ["==", "!="])
def test_empty_bytes_comparison(get_contract_with_gas_estimation, length, value, result, op):
    contract = f"""
@external
def foo(xs: Bytes[{length}]) -> bool:
    return b"" {op} xs
    """
    c = get_contract_with_gas_estimation(contract)
    if op == "==":
        assert c.foo(value) == result
    elif op == "!=":
        assert c.foo(value) != result
