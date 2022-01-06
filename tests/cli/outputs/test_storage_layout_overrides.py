from vyper.compiler import compile_code


def test_storage_layout_overrides():
    code = """
a: uint256
b: uint256"""

    storage_layout_overrides = {
        "a": {"type": "uint256", "location": "storage", "slot": 1},
        "b": {"type": "uint256", "location": "storage", "slot": 0},
    }

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_overrides
    )

    assert out["layout"] == {
        "a": {"type": "uint256", "location": "storage", "slot": 1},
        "b": {"type": "uint256", "location": "storage", "slot": 0},
    }


def test_storage_layout_for_more_complex():
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

    storage_layout_override = {
        "nonreentrant.foo": {"type": "nonreentrant lock", "location": "storage", "slot": 8},
        "nonreentrant.bar": {"type": "nonreentrant lock", "location": "storage", "slot": 7},
        "foo": {
            "type": "HashMap[address, uint256]",
            "location": "storage",
            "slot": 1,
        },
        "baz": {"type": "Bytes[65]", "location": "storage", "slot": 2},
        "bar": {"type": "uint256", "location": "storage", "slot": 6},
    }

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_override
    )

    assert out["layout"] == {
        "nonreentrant.foo": {"type": "nonreentrant lock", "location": "storage", "slot": 8},
        "nonreentrant.bar": {"type": "nonreentrant lock", "location": "storage", "slot": 7},
        "foo": {
            "type": "HashMap[address, uint256]",
            "location": "storage",
            "slot": 1,
        },
        "baz": {"type": "Bytes[65]", "location": "storage", "slot": 2},
        "bar": {"type": "uint256", "location": "storage", "slot": 6},
    }
