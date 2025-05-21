import re

import pytest

from vyper.cli.vyper_json import compile_json
from vyper.compiler import compile_code
from vyper.evm.opcodes import version_check
from vyper.exceptions import StorageLayoutException


def test_storage_layout_overrides():
    code = """
a: uint256
b: uint256"""

    storage_layout_overrides = {
        "a": {"type": "uint256", "slot": 5, "n_slots": 1},
        "b": {"type": "uint256", "slot": 0, "n_slots": 1},
    }

    expected_output = {"storage_layout": storage_layout_overrides}

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_overrides
    )

    assert out["layout"] == expected_output


def test_storage_layout_overrides_json():
    code = """
a: uint256
b: uint256"""

    storage_layout_overrides = {
        "a": {"type": "uint256", "slot": 5, "n_slots": 1},
        "b": {"type": "uint256", "slot": 0, "n_slots": 1},
    }

    input_json = {
        "language": "Vyper",
        "sources": {"contracts/foo.vy": {"content": code}},
        "storage_layout_overrides": {"contracts/foo.vy": storage_layout_overrides},
        "settings": {"outputSelection": {"*": ["*"]}},
    }

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_overrides
    )
    assert (
        compile_json(input_json)["contracts"]["contracts/foo.vy"]["foo"]["layout"] == out["layout"]
    )


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
        "$.nonreentrant_key": {"type": "nonreentrant lock", "slot": 8, "n_slots": 1},
        "foo": {"type": "HashMap[address, uint256]", "slot": 1, "n_slots": 1},
        "baz": {"type": "Bytes[65]", "slot": 2, "n_slots": 4},
        "bar": {"type": "uint256", "slot": 6, "n_slots": 1},
    }
    if version_check(begin="cancun"):
        del storage_layout_override["$.nonreentrant_key"]

    expected_output = {"storage_layout": storage_layout_override}

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_override
    )

    # adjust transient storage layout
    if version_check(begin="cancun"):
        expected_output["transient_storage_layout"] = {
            "$.nonreentrant_key": {"n_slots": 1, "slot": 0, "type": "nonreentrant lock"}
        }

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

    if version_check(begin="cancun"):
        del storage_layout_override["$.nonreentrant_key"]
        assert (
            compile_code(
                code, output_formats=["layout"], storage_layout_override=storage_layout_override
            )
            is not None
        )

    else:
        exception_regex = re.escape(
            f"Invalid storage slot for var $.nonreentrant_key, out of bounds: {2**256}"
        )
        with pytest.raises(StorageLayoutException, match=exception_regex):
            compile_code(
                code, output_formats=["layout"], storage_layout_override=storage_layout_override
            )


def test_override_missing_nonreentrant_key():
    code = """
@nonreentrant
@external
def foo():
    pass
    """

    storage_layout_override = {}

    if version_check(begin="cancun"):
        assert (
            compile_code(
                code, output_formats=["layout"], storage_layout_override=storage_layout_override
            )
            is not None
        )
        # in cancun, nonreentrant key is allocated in transient storage and can't be overridden
        return
    else:
        exception_regex = re.escape(
            "Could not find storage slot for $.nonreentrant_key."
            " Have you used the correct storage layout file?"
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
        match="Could not find storage slot for symbol. "
        "Have you used the correct storage layout file?",
    ):
        compile_code(
            code, output_formats=["layout"], storage_layout_override=storage_layout_override
        )


@pytest.mark.requires_evm_version("cancun")
def test_override_with_immutables_and_transient():
    code = """
some_local: transient(uint256)
some_immutable: immutable(uint256)
name: public(String[64])

@deploy
def __init__():
    some_immutable = 5
    """

    storage_layout_override = {"name": {"slot": 10, "type": "String[64]", "n_slots": 3}}

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_override
    )

    expected_output = {
        "storage_layout": storage_layout_override,
        "transient_storage_layout": {"some_local": {"slot": 1, "type": "uint256", "n_slots": 1}},
        "code_layout": {"some_immutable": {"offset": 0, "type": "uint256", "length": 32}},
    }

    assert out["layout"] == expected_output


def test_override_modules(make_input_bundle):
    # test module storage layout, with initializes in an imported module
    # note code repetition with test_storage_layout.py; maybe refactor to
    # some fixtures
    lib1 = """
supply: uint256
SYMBOL: immutable(String[32])
DECIMALS: immutable(uint8)

@deploy
def __init__():
    SYMBOL = "VYPR"
    DECIMALS = 18
    """
    lib2 = """
import lib1

initializes: lib1

counter: uint256
storage_variable: uint256
immutable_variable: immutable(uint256)

@deploy
def __init__(s: uint256):
    immutable_variable = s
    lib1.__init__()

@internal
def decimals() -> uint8:
    return lib1.DECIMALS
    """
    code = """
import lib1 as a_library
import lib2

counter: uint256  # test shadowing
some_immutable: immutable(DynArray[uint256, 10])

# for fun: initialize lib2 in front of lib1
initializes: lib2

counter2: uint256

uses: a_library

@deploy
def __init__():
    some_immutable = [1, 2, 3]

    lib2.__init__(17)

@external
def foo() -> uint256:
    return a_library.supply
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    override = {
        "counter": {"slot": 5, "type": "uint256", "n_slots": 1},
        "lib2": {
            "lib1": {"supply": {"slot": 12, "type": "uint256", "n_slots": 1}},
            "storage_variable": {"slot": 34, "type": "uint256", "n_slots": 1},
            "counter": {"slot": 15, "type": "uint256", "n_slots": 1},
        },
        "counter2": {"slot": 171, "type": "uint256", "n_slots": 1},
    }
    out = compile_code(
        code, output_formats=["layout"], input_bundle=input_bundle, storage_layout_override=override
    )

    expected_output = {
        "storage_layout": override,
        "code_layout": {
            "some_immutable": {"length": 352, "offset": 0, "type": "DynArray[uint256, 10]"},
            "lib2": {
                "lib1": {
                    "SYMBOL": {"length": 64, "offset": 352, "type": "String[32]"},
                    "DECIMALS": {"length": 32, "offset": 416, "type": "uint8"},
                },
                "immutable_variable": {"length": 32, "offset": 448, "type": "uint256"},
            },
        },
    }

    assert out["layout"] == expected_output


def test_module_collision(make_input_bundle):
    # test collisions between modules which are "siblings" in the import tree
    # some fixtures
    lib1 = """
supply: uint256
    """
    lib2 = """
counter: uint256
    """
    code = """
import lib1 as a_library
import lib2

# for fun: initialize lib2 in front of lib1
initializes: lib2
initializes: a_library
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    override = {
        "lib2": {"counter": {"slot": 15, "type": "uint256", "n_slots": 1}},
        "a_library": {"supply": {"slot": 15, "type": "uint256", "n_slots": 1}},
    }

    with pytest.raises(
        StorageLayoutException,
        match="Storage collision! Tried to assign 'a_library.supply' to"
        " slot 15 but it has already been reserved by 'lib2.counter'",
    ):
        compile_code(
            code,
            output_formats=["layout"],
            input_bundle=input_bundle,
            storage_layout_override=override,
        )


def test_module_collision2(make_input_bundle):
    # test "parent-child" collisions
    lib1 = """
supply: uint256
    """
    code = """
import lib1

counter: uint256

initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    override = {
        "counter": {"slot": 15, "type": "uint256", "n_slots": 1},
        "lib1": {"supply": {"slot": 15, "type": "uint256", "n_slots": 1}},
    }

    with pytest.raises(
        StorageLayoutException,
        match="Storage collision! Tried to assign 'lib1.supply' to"
        " slot 15 but it has already been reserved by 'counter'",
    ):
        compile_code(
            code,
            output_formats=["layout"],
            input_bundle=input_bundle,
            storage_layout_override=override,
        )


def test_module_overlap(make_input_bundle):
    # test a collision which only overlaps on one word
    lib1 = """
supply: uint256[2]
    """
    code = """
import lib1

counter: uint256[2]

initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    override = {
        "counter": {"slot": 15, "type": "uint256[2]", "n_slots": 2},
        "lib1": {"supply": {"slot": 16, "type": "uint256[2]", "n_slots": 2}},
    }

    with pytest.raises(
        StorageLayoutException,
        match="Storage collision! Tried to assign 'lib1.supply' to"
        " slot 16 but it has already been reserved by 'counter'",
    ):
        compile_code(
            code,
            output_formats=["layout"],
            input_bundle=input_bundle,
            storage_layout_override=override,
        )


def test_override_with_nonreentrant_pragma(make_input_bundle):
    code = """
# pragma nonreentrancy on
a: public(uint256)
    """

    if version_check(begin="cancun"):
        override = {"a": {"type": "uint256", "n_slots": 1, "slot": 0}}
    else:
        override = {
            "a": {"type": "uint256", "n_slots": 1, "slot": 0},
            "$.nonreentrant_key": {"type": "nonreentrant lock", "n_slots": 1, "slot": 20},
        }

    # note: compile_code checks roundtrip of the override
    compile_code(code, storage_layout_override=override)
