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


def test_multiple_immutable_values(get_contract):
    code = """
a: immutable(uint256)
b: immutable(address)
c: immutable(String[64])

@external
def __init__(_a: uint256, _b: address, _c: String[64]):
    a = _a
    b = _b
    c = _c

@view
@external
def get_values() -> (uint256, address, String[64]):
    return a, b, c
    """
    values = (3, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", "Hello world")
    c = get_contract(code, *values)
    assert c.get_values() == list(values)
