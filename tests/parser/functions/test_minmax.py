from decimal import (
    Decimal,
)


def test_minmax(get_contract_with_gas_estimation):
    minmax_test = """
@public
def foo() -> decimal:
    return min(3.0, 5.0) + max(10.0, 20.0) + min(200.1, 400.0) + max(3000.0, 8000.02) + min(50000.003, 70000.004)  # noqa: E501

@public
def goo() -> uint256:
    return min(convert(3, uint256), convert(5, uint256)) + max(convert(40, uint256), convert(80, uint256))
    """

    c = get_contract_with_gas_estimation(minmax_test)
    assert c.foo() == Decimal('58223.123')
    assert c.goo() == 83

    print("Passed min/max test")


def test_max_var_uint256_literal_int128(get_contract_with_gas_estimation):
    """
    Tests to verify that max works as expected when a variable/literal uint256
    and a literal int128 are passed.
    """
    code = """
@public
def foo() -> uint256:
    a: uint256 = 2 ** 200
    b: uint256 = 5
    return max(a, 5) + max(b, 5)

@public
def goo() -> uint256:
    a: uint256 = 2 ** 200
    b: uint256 = 5
    return max(5, a) + max(5, b)

@public
def bar() -> uint256:
    a: uint256 = 2
    b: uint256 = 5
    return max(a, 5) + max(b, 5)

@public
def baz() -> uint256:
    a: uint256 = 2
    b: uint256 = 5
    return max(5, a) + max(5, b)

@public
def both_literals() -> uint256:
    return max(2 ** 200, 2)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 2 ** 200 + 5
    assert c.goo() == 2 ** 200 + 5
    assert c.bar() == 5 + 5
    assert c.baz() == 5 + 5
    assert c.both_literals() == 2 ** 200


def test_min_var_uint256_literal_int128(get_contract_with_gas_estimation):
    """
    Tests to verify that max works as expected when a variable/literal uint256
    and a literal int128 are passed.
    """
    code = """
@public
def foo() -> uint256:
    a: uint256 = 2 ** 200
    b: uint256 = 5
    return min(a, 5) + min(b, 5)

@public
def goo() -> uint256:
    a: uint256 = 2 ** 200
    b: uint256 = 5
    return min(5, a) + min(5, b)

@public
def bar() -> uint256:
    a: uint256 = 2
    b: uint256 = 5
    return min(a, 5) + min(b, 5)

@public
def baz() -> uint256:
    a: uint256 = 2
    b: uint256 = 5
    return min(5, a) + min(5, b)

@public
def both_literals() -> uint256:
    return min(2 ** 200, 2)
"""
    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 5 + 5
    assert c.goo() == 5 + 5
    assert c.bar() == 2 + 5
    assert c.baz() == 2 + 5
    assert c.both_literals() == 2


def test_minmax_var_uint256_var_int128(get_contract_with_gas_estimation, assert_compile_failed):
    """
    Tests to verify that max throws an error if a variable uint256 and a
    variable int128 are passed.
    """
    from vyper.exceptions import TypeMismatch
    code_1 = """
@public
def foo() -> uint256:
    a: uint256 = 2
    b: int128 = 3
    return max(a, b)
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code_1),
        TypeMismatch
    )

    code_2 = """
@public
def foo() -> uint256:
    a: uint256 = 2
    b: int128 = 3
    return max(b, a)
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code_2),
        TypeMismatch
    )

    code_3 = """
@public
def foo() -> uint256:
    a: uint256 = 2
    b: int128 = 3
    return min(a, b)
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code_3),
        TypeMismatch
    )

    code_4 = """
@public
def foo() -> uint256:
    a: uint256 = 2
    b: int128 = 3
    return min(b, a)
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code_4),
        TypeMismatch
    )


def test_minmax_var_uint256_negative_int128(get_contract_with_gas_estimation,
                                            assert_tx_failed,
                                            assert_compile_failed):
    from vyper.exceptions import TypeMismatch
    code_1 = """
@public
def foo() -> uint256:
    a: uint256 = 2 ** 200
    return max(a, -1)
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code_1),
        TypeMismatch
    )

    code_2 = """
@public
def foo() -> uint256:
    a: uint256 = 2 ** 200
    return min(a, -1)
"""
    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code_2),
        TypeMismatch
    )


def test_unsigned(get_contract_with_gas_estimation):
    code = """
@public
def foo1() -> uint256:
    return min(0, 2**255)

@public
def foo2() -> uint256:
    return min(2**255, 0)

@public
def foo3() -> uint256:
    return max(0, 2**255)

@public
def foo4() -> uint256:
    return max(2**255, 0)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo1() == 0
    assert c.foo2() == 0
    assert c.foo3() == 2**255
    assert c.foo4() == 2**255


def test_signed(get_contract_with_gas_estimation):
    code = """
@public
def foo1() -> int128:
    return min(MIN_INT128, MAX_INT128)

@public
def foo2() -> int128:
    return min(MAX_INT128, MIN_INT128)

@public
def foo3() -> int128:
    return max(MIN_INT128, MAX_INT128)

@public
def foo4() -> int128:
    return max(MAX_INT128, MIN_INT128)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo1() == -2**127
    assert c.foo2() == -2**127
    assert c.foo3() == 2**127-1
    assert c.foo4() == 2**127-1
