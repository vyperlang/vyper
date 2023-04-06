from vyper.compiler import compile_code


def test_storage_layout():
    code = """
foo: HashMap[address, uint256]

@external
@nonreentrant("foo")
def public_foo1():
    pass

@external
@nonreentrant("foo")
def public_foo2():
    pass


@internal
@nonreentrant("bar")
def _bar():
    pass

arr: DynArray[uint256, 3]

# mix it up a little
baz: Bytes[65]
bar: uint256

@external
@nonreentrant("bar")
def public_bar():
    pass

@external
@nonreentrant("foo")
def public_foo3():
    pass
    """

    out = compile_code(code, output_formats=["layout"])

    assert out["layout"]["storage_layout"] == {
        "nonreentrant.foo": {"type": "nonreentrant lock", "slot": 0},
        "nonreentrant.bar": {"type": "nonreentrant lock", "slot": 1},
        "foo": {"type": "HashMap[address, uint256]", "slot": 2},
        "arr": {"type": "DynArray[uint256, 3]", "slot": 3},
        "baz": {"type": "Bytes[65]", "slot": 7},
        "bar": {"type": "uint256", "slot": 11},
    }


def test_storage_and_immutables_layout():
    code = """
name: String[32]
SYMBOL: immutable(String[32])
DECIMALS: immutable(uint8)

@external
def __init__():
    SYMBOL = "VYPR"
    DECIMALS = 18
    """

    expected_layout = {
        "code_layout": {
            "DECIMALS": {"length": 32, "offset": 64, "type": "uint8"},
            "SYMBOL": {"length": 64, "offset": 0, "type": "String[32]"},
        },
        "storage_layout": {"name": {"slot": 0, "type": "String[32]"}},
    }

    out = compile_code(code, output_formats=["layout"])
    assert out["layout"] == expected_layout
