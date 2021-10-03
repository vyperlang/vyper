import pytest

from vyper import compile_code

fail_list = [
    # VALUE is not set in the constructor
    """
VALUE: immutable(uint256)

@external
def __init__():
    pass
    """,
    # no `__init__` function, VALUE not set
    """
VALUE: immutable(uint256)

@view
@external
def get_value() -> uint256:
    return VALUE
    """,
    # VALUE given an initial value
    """
VALUE: immutable(uint256) = 3

@external
def __init__():
    pass
    """,
    # setting value outside of constructor
    """
VALUE: immutable(uint256)

@external
def __init__():
    VALUE = 0

@external
def set_value(_value: uint256):
    VALUE = _value
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_compilation_fails_with_exception(bad_code):
    with pytest.raises(Exception):
        compile_code(bad_code)


pass_list = [
    f"""
VALUE: immutable({typ})

@external
def __init__(_value: {typ}):
    VALUE = _value

@view
@external
def get_value() -> {typ}:
    return VALUE
    """
    for typ in (
        "uint256",
        "int256",
        "int128",
        "address",
        "Bytes[64]",
        "bytes32",
        "decimal",
        "bool",
        "String[10]",
    )
]

pass_list += [
    # using immutable allowed in constructor
    """
VALUE: immutable(uint256)

@external
def __init__(_value: uint256):
    VALUE = _value * 3
    VALUE = VALUE + 1
    """
]


@pytest.mark.parametrize("good_code", pass_list)
def test_compilation_passes(good_code):
    assert compile_code(good_code)
