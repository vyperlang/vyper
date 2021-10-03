import pytest

code_list = [
    (
        f"""
VALUE: immutable({typ})

@external
def __init__(_value: {typ}):
    VALUE = _value

@view
@external
def get_value() -> {typ}:
    return VALUE
    """,
        value,
    )
    for typ, value in (
        ("uint256", 42),
        ("int256", -(2 ** 200)),
        ("int128", -(2 ** 126)),
        ("address", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"),
        ("bytes32", b"deadbeef" * 4),
        ("bool", True),
    )
]


@pytest.mark.parametrize("code,value", code_list)
def test_value_is_stored_correctly(code, value, get_contract):
    c = get_contract(code, value)
    assert c.get_value() == value


def test_simple_usage(get_contract):
    code = """
VALUE: immutable(uint256)

@external
def __init__(_value: uint256):
    VALUE = _value

@view
@external
def get_value() -> uint256:
    return VALUE
"""
    c = get_contract(code, 42)
    assert c.get_value() == 42
