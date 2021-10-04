import pytest

type_list = (
    ("uint256", 42),
    ("int256", -(2 ** 200)),
    ("int128", -(2 ** 126)),
    ("address", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"),
    ("bytes32", b"deadbeef" * 4),
    ("bool", True),
    ("String[10]", "Vyper hiss"),
    ("Bytes[10]", b"Vyper hiss"),
)


@pytest.mark.parametrize("typ,value", type_list)
def test_value_storage_retrieval(typ, value, get_contract):
    code = f"""
VALUE: immutable({typ})

@external
def __init__(_value: {typ}):
    VALUE = _value

@view
@external
def get_value() -> {typ}:
    return VALUE
    """

    c = get_contract(code, value)
    assert c.get_value() == value
