from vyper.exceptions import InvalidLiteral, SyntaxException


def test_no_none_assign(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
        """
@external
def foo():
    bar: int128 = 0
    bar = None
    """,
        """
@external
def foo():
    bar: uint256 = 0
    bar = None
    """,
        """
@external
def foo():
    bar: bool = False
    bar = None
    """,
        """
@external
def foo():
    bar: decimal = 0.0
    bar = None
    """,
        """
@external
def foo():
    bar: bytes32 = EMPTY_BYTES32
    bar = None
    """,
        """
@external
def foo():
    bar: address = ZERO_ADDRESS
    bar = None
    """,
        """
@external
def foo():
    bar: int128 = None
    """,
        """
@external
def foo():
    bar: uint256 = None
    """,
        """
@external
def foo():
    bar: bool = None
    """,
        """
@external
def foo():
    bar: decimal = None
    """,
        """
@external
def foo():
    bar: bytes32 = None
    """,
        """
@external
def foo():
    bar: address = None
    """,
    ]

    for contract in contracts:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), InvalidLiteral)


def test_no_is_none(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
        """
@external
def foo():
    bar: int128 = 0
    assert bar is None
    """,
        """
@external
def foo():
    bar: uint256 = 0
    assert bar is None
    """,
        """
@external
def foo():
    bar: bool = False
    assert bar is None
    """,
        """
@external
def foo():
    bar: decimal = 0.0
    assert bar is None
    """,
        """
@external
def foo():
    bar: bytes32 = EMPTY_BYTES32
    assert bar is None
    """,
        """
@external
def foo():
    bar: address = ZERO_ADDRESS
    assert bar is None
    """,
    ]

    for contract in contracts:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), SyntaxException)


def test_no_eq_none(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
        """
@external
def foo():
    bar: int128 = 0
    assert bar == None
    """,
        """
@external
def foo():
    bar: uint256 = 0
    assert bar == None
    """,
        """
@external
def foo():
    bar: bool = False
    assert bar == None
    """,
        """
@external
def foo():
    bar: decimal = 0.0
    assert bar == None
    """,
        """
@external
def foo():
    bar: bytes32 = EMPTY_BYTES32
    assert bar == None
    """,
        """
@external
def foo():
    bar: address = ZERO_ADDRESS
    assert bar == None
    """,
    ]

    for contract in contracts:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), InvalidLiteral)


def test_struct_none(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [  # noqa: E122
        """
struct Mom:
    a: uint256
    b: int128

@external
def foo():
    mom: Mom = Mom({a: None, b: 0})
    """,
        """
struct Mom:
    a: uint256
    b: int128

@external
def foo():
    mom: Mom = Mom({a: 0, b: None})
    """,
        """
struct Mom:
    a: uint256
    b: int128

@external
def foo():
    mom: Mom = Mom({a: None, b: None})
    """,
    ]

    for contract in contracts:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), InvalidLiteral)
