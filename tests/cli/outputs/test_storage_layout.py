from vyper.compiler import compile_code


def test_method_identifiers():
    code = """
foo: HashMap[address, uint256]
baz: Bytes[65]
bar: uint256

@external
@nonreentrant("foo")
def public_foo():
    pass

@internal
@nonreentrant("bar")
def _bar():
    pass

@external
@nonreentrant("bar")
def public_bar():
    pass
    """

    out = compile_code(code, output_formats=["layout"],)

    assert out["layout"] == {
        "nonreentrant.foo": {"type": "nonreentrant lock", "location": "storage", "slot": 0},
        "nonreentrant.bar": {"type": "nonreentrant lock", "location": "storage", "slot": 2},
        "foo": {
            "type": "HashMap[address, uint256][address, uint256]",
            "location": "storage",
            "slot": 3,
        },
        "baz": {"type": "Bytes[65]", "location": "storage", "slot": 4},
        "bar": {"type": "uint256", "location": "storage", "slot": 8},
    }
