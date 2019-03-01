from vyper.exceptions import (
    InvalidLiteralException
)


def test_no_none_assign(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
    """
@public
def foo():
    bar: int128
    bar = None
    """,
    """
@public
def foo():
    bar: uint256
    bar = None
    """,
    """
@public
def foo():
    bar: bool
    bar = None
    """,
    """
@public
def foo():
    bar: decimal
    bar = None
    """,
    """
@public
def foo():
    bar: bytes32
    bar = None
    """,
    """
@public
def foo():
    bar: address
    bar = None
    """,
    """
@public
def foo():
    bar: int128 = None
    """,
    """
@public
def foo():
    bar: uint256 = None
    """,
    """
@public
def foo():
    bar: bool = None
    """,
    """
@public
def foo():
    bar: decimal = None
    """,
    """
@public
def foo():
    bar: bytes32 = None
    """,
    """
@public
def foo():
    bar: address = None
    """
    ]

    for contract in contracts:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract),
            InvalidLiteralException
        )


def test_no_is_none(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
    """
@public
def foo():
    bar: int128
    assert bar is None
    """,
    """
@public
def foo():
    bar: uint256
    assert bar is None
    """,
    """
@public
def foo():
    bar: bool
    assert bar is None
    """,
    """
@public
def foo():
    bar: decimal
    assert bar is None
    """,
    """
@public
def foo():
    bar: bytes32
    assert bar is None
    """,
    """
@public
def foo():
    bar: address
    assert bar is None
    """
    ]

    for contract in contracts:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract),
            InvalidLiteralException
        )


def test_no_eq_none(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
    """
@public
def foo():
    bar: int128
    assert bar == None
    """,
    """
@public
def foo():
    bar: uint256
    assert bar == None
    """,
    """
@public
def foo():
    bar: bool
    assert bar == None
    """,
    """
@public
def foo():
    bar: decimal
    assert bar == None
    """,
    """
@public
def foo():
    bar: bytes32
    assert bar == None
    """,
    """
@public
def foo():
    bar: address
    assert bar == None
    """
    ]

    for contract in contracts:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract),
            InvalidLiteralException
        )


def test_struct_none(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
    """
struct Mom:
    a: uint256
    b: int128

@public
def foo():
    mom: Mom = Mom({a: None, b: 0})
    """,
    """
struct Mom:
    a: uint256
    b: int128

@public
def foo():
    mom: Mom = Mom({a: 0, b: None})
    """,
    """
struct Mom:
    a: uint256
    b: int128

@public
def foo():
    mom: Mom = Mom({b: None, a: 0})
    """,
    """
struct Mom:
    a: uint256
    b: int128

@public
def foo():
    mom: Mom = Mom({a: None, b: None})
    """
    ]

    for contract in contracts:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract),
            InvalidLiteralException
        )
