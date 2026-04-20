import pytest

from vyper.exceptions import InvalidType, UnknownType
from vyper.compiler import compile_code

fail_list = [
    """
x: bat
    """,
    """
x: HashMap[int, int128]
    """,
    """
struct A:
    b: B
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_unknown_type_exception(bad_code, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), UnknownType)


invalid_list = [
    # Must be a literal string.
    """
@external
def mint(_to: address, _value: uint256):
    assert msg.sender == self,msg.sender
    """,
    # Raise reason must be string
    """
@external
def mint(_to: address, _value: uint256):
    raise 1
    """,
    """
x: int128[3.5]
    """,
    # Key of mapping must be a base type
    """
b: HashMap[(int128, decimal), int128]
    """,
    """
x: String <= 33
    """,
    """
x: Bytes <= wei
    """,
    """
x: 5
    """,
]


@pytest.mark.parametrize("bad_code", invalid_list)
def test_invalid_type_exception(bad_code, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), InvalidType)


def test_constant_name_not_a_type_function_param():
    code = """
N: constant(uint256) = 1

@external
def foo(x: N):
    pass
    """
    with pytest.raises(InvalidType, match="is not a type"):
        compile_code(code)


def test_constant_name_not_a_type_return_type():
    code = """
N: constant(uint256) = 1

@external
def foo() -> N:
    pass
    """
    with pytest.raises(InvalidType, match="is not a type"):
        compile_code(code)


def test_constant_name_not_a_type_state_variable():
    code = """
N: constant(uint256) = 1
x: N
    """
    with pytest.raises(InvalidType, match="is not a type"):
        compile_code(code)


def test_constant_name_not_a_type_convert():
    code = """
N: constant(uint256) = 1

@external
def foo():
    y: uint8 = 1
    x: uint256 = convert(y, N)
    """
    with pytest.raises(InvalidType, match="is not a type"):
        compile_code(code)


def test_constant_name_not_a_type_static_array():
    code = f"""
N: constant(uint8[3]) = [1, 2, 3]
x: N
    """
    with pytest.raises(InvalidType, match="is not a type"):
        compile_code(code)


def test_constant_name_not_a_type_dynamic_array():
    code = f"""
bar: DynArray[uint8, 3]

@external
def foo():
    x: DynArray[uint8, 3] = empty(self.bar)
    """
    with pytest.raises(InvalidType, match="is not a type"):
        compile_code(code)
