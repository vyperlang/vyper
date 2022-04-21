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

    out = compile_code(
        code,
        output_formats=["layout"],
    )

    assert out["layout"] == {
        "nonreentrant.foo": {"type": "nonreentrant lock", "location": "storage", "slot": 0},
        "nonreentrant.bar": {"type": "nonreentrant lock", "location": "storage", "slot": 1},
        "foo": {
            "type": "HashMap[address, uint256]",
            "location": "storage",
            "slot": 2,
        },
        "arr": {
            "type": "DynArray[uint256, 3]",
            "location": "storage",
            "slot": 3,
        },
        "baz": {"type": "Bytes[65]", "location": "storage", "slot": 7},
        "bar": {"type": "uint256", "location": "storage", "slot": 11},
    }
