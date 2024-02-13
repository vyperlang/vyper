import re

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StorageLayoutException


def test_storage_layout_overrides():
    code = """
a: uint256
b: uint256"""

    storage_layout_overrides = {
        "a": {"type": "uint256", "slot": 1},
        "b": {"type": "uint256", "slot": 0},
    }

    expected_output = {"storage_layout": storage_layout_overrides, "code_layout": {}}

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_overrides
    )

    assert out["layout"] == expected_output


def test_storage_layout_for_more_complex():
    code = """
foo: HashMap[address, uint256]

@external
@nonreentrant
def public_foo1():
    pass

@external
@nonreentrant
def public_foo2():
    pass


@internal
@nonreentrant
def _bar():
    pass

# mix it up a little
baz: Bytes[65]
bar: uint256

@external
@nonreentrant
def public_bar():
    pass

@external
@nonreentrant
def public_foo3():
    pass
    """

    storage_layout_override = {
        "$.nonreentrant_key": {"type": "nonreentrant lock", "slot": 8},
        "foo": {"type": "HashMap[address, uint256]", "slot": 1},
        "baz": {"type": "Bytes[65]", "slot": 2},
        "bar": {"type": "uint256", "slot": 6},
    }

    expected_output = {"storage_layout": storage_layout_override, "code_layout": {}}

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_override
    )

    assert out["layout"] == expected_output


def test_simple_collision():
    code = """
name: public(String[64])
symbol: public(String[32])"""

    storage_layout_override = {
        "name": {"slot": 0, "type": "String[64]"},
        "symbol": {"slot": 1, "type": "String[32]"},
    }

    with pytest.raises(
        StorageLayoutException,
        match="Storage collision! Tried to assign 'symbol' to slot 1"
        " but it has already been reserved by 'name'",
    ):
        compile_code(
            code, output_formats=["layout"], storage_layout_override=storage_layout_override
        )


def test_overflow():
    code = """
x: uint256[2]
    """

    storage_layout_override = {"x": {"slot": 2**256 - 1, "type": "uint256[2]"}}

    with pytest.raises(
        StorageLayoutException, match=f"Invalid storage slot for var x, out of bounds: {2**256}"
    ):
        compile_code(
            code, output_formats=["layout"], storage_layout_override=storage_layout_override
        )


def test_override_nonreentrant_slot():
    code = """
@nonreentrant
@external
def foo():
    pass
    """

    storage_layout_override = {"$.nonreentrant_key": {"slot": 2**256, "type": "nonreentrant key"}}

    exception_regex = re.escape(
        f"Invalid storage slot for var $.nonreentrant_key, out of bounds: {2**256}"
    )
    with pytest.raises(StorageLayoutException, match=exception_regex):
        compile_code(
            code, output_formats=["layout"], storage_layout_override=storage_layout_override
        )


def test_incomplete_overrides():
    code = """
name: public(String[64])
symbol: public(String[32])"""

    storage_layout_override = {"name": {"slot": 0, "type": "String[64]"}}

    with pytest.raises(
        StorageLayoutException,
        match="Could not find storage_slot for symbol. "
        "Have you used the correct storage layout file?",
    ):
        compile_code(
            code, output_formats=["layout"], storage_layout_override=storage_layout_override
        )
