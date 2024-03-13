from vyper.compiler import compile_code


def test_storage_layout():
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

arr: DynArray[uint256, 3]

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

    out = compile_code(code, output_formats=["layout"])

    assert out["layout"]["storage_layout"] == {
        "$.nonreentrant_key": {"slot": 0, "type": "nonreentrant lock"},
        "foo": {"slot": 1, "type": "HashMap[address, uint256]"},
        "arr": {"slot": 2, "type": "DynArray[uint256, 3]"},
        "baz": {"slot": 6, "type": "Bytes[65]"},
        "bar": {"slot": 10, "type": "uint256"},
    }


def test_storage_and_immutables_layout():
    code = """
name: String[32]
SYMBOL: immutable(String[32])
DECIMALS: immutable(uint8)

@deploy
def __init__():
    SYMBOL = "VYPR"
    DECIMALS = 18
    """

    expected_layout = {
        "code_layout": {
            "SYMBOL": {"length": 64, "offset": 0, "type": "String[32]"},
            "DECIMALS": {"length": 32, "offset": 64, "type": "uint8"},
        },
        "storage_layout": {
            "$.nonreentrant_key": {"slot": 0, "type": "nonreentrant lock"},
            "name": {"slot": 1, "type": "String[32]"},
        },
    }

    out = compile_code(code, output_formats=["layout"])
    assert out["layout"] == expected_layout


def test_storage_layout_module(make_input_bundle):
    lib1 = """
supply: uint256
SYMBOL: immutable(String[32])
DECIMALS: immutable(uint8)

@deploy
def __init__():
    SYMBOL = "VYPR"
    DECIMALS = 18
    """
    code = """
import lib1 as a_library

counter: uint256
some_immutable: immutable(DynArray[uint256, 10])

counter2: uint256

initializes: a_library

@deploy
def __init__():
    some_immutable = [1, 2, 3]
    a_library.__init__()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})

    expected_layout = {
        "code_layout": {
            "some_immutable": {"length": 352, "offset": 0, "type": "DynArray[uint256, 10]"},
            "a_library": {
                "SYMBOL": {"length": 64, "offset": 352, "type": "String[32]"},
                "DECIMALS": {"length": 32, "offset": 416, "type": "uint8"},
            },
        },
        "storage_layout": {
            "$.nonreentrant_key": {"slot": 0, "type": "nonreentrant lock"},
            "counter": {"slot": 1, "type": "uint256"},
            "counter2": {"slot": 2, "type": "uint256"},
            "a_library": {"supply": {"slot": 3, "type": "uint256"}},
        },
    }

    out = compile_code(code, input_bundle=input_bundle, output_formats=["layout"])
    assert out["layout"] == expected_layout


def test_storage_layout_module2(make_input_bundle):
    # test module storage layout, but initializes is in a different order
    lib1 = """
supply: uint256
SYMBOL: immutable(String[32])
DECIMALS: immutable(uint8)

@deploy
def __init__():
    SYMBOL = "VYPR"
    DECIMALS = 18
    """
    code = """
import lib1 as a_library

counter: uint256
some_immutable: immutable(DynArray[uint256, 10])

initializes: a_library

counter2: uint256

@deploy
def __init__():
    a_library.__init__()
    some_immutable = [1, 2, 3]
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    expected_layout = {
        "code_layout": {
            "some_immutable": {"length": 352, "offset": 0, "type": "DynArray[uint256, 10]"},
            "a_library": {
                "SYMBOL": {"length": 64, "offset": 352, "type": "String[32]"},
                "DECIMALS": {"length": 32, "offset": 416, "type": "uint8"},
            },
        },
        "storage_layout": {
            "$.nonreentrant_key": {"slot": 0, "type": "nonreentrant lock"},
            "counter": {"slot": 1, "type": "uint256"},
            "a_library": {"supply": {"slot": 2, "type": "uint256"}},
            "counter2": {"slot": 3, "type": "uint256"},
        },
    }

    out = compile_code(code, input_bundle=input_bundle, output_formats=["layout"])
    assert out["layout"] == expected_layout


def test_storage_layout_module_uses(make_input_bundle):
    # test module storage layout, with initializes/uses and a nonreentrant
    # lock
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

uses: lib1

storage_variable: uint256
immutable_variable: immutable(uint256)

@deploy
def __init__(s: uint256):
    immutable_variable = s

@internal
def decimals() -> uint8:
    return lib1.DECIMALS

@external
@nonreentrant
def foo():
    pass
    """
    code = """
import lib1 as a_library
import lib2

counter: uint256
some_immutable: immutable(DynArray[uint256, 10])

# for fun: initialize lib2 in front of lib1
initializes: lib2[lib1 := a_library]

counter2: uint256

initializes: a_library

@deploy
def __init__():
    a_library.__init__()
    some_immutable = [1, 2, 3]

    lib2.__init__(17)

@external
@nonreentrant
def bar():
    pass
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    expected_layout = {
        "code_layout": {
            "some_immutable": {"length": 352, "offset": 0, "type": "DynArray[uint256, 10]"},
            "lib2": {"immutable_variable": {"length": 32, "offset": 352, "type": "uint256"}},
            "a_library": {
                "SYMBOL": {"length": 64, "offset": 384, "type": "String[32]"},
                "DECIMALS": {"length": 32, "offset": 448, "type": "uint8"},
            },
        },
        "storage_layout": {
            "$.nonreentrant_key": {"slot": 0, "type": "nonreentrant lock"},
            "counter": {"slot": 1, "type": "uint256"},
            "lib2": {"storage_variable": {"slot": 2, "type": "uint256"}},
            "counter2": {"slot": 3, "type": "uint256"},
            "a_library": {"supply": {"slot": 4, "type": "uint256"}},
        },
    }

    out = compile_code(code, input_bundle=input_bundle, output_formats=["layout"])
    assert out["layout"] == expected_layout


def test_storage_layout_module_nested_initializes(make_input_bundle):
    # test module storage layout, with initializes in an imported module
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

counter: uint256
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

    expected_layout = {
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
        "storage_layout": {
            "$.nonreentrant_key": {"slot": 0, "type": "nonreentrant lock"},
            "counter": {"slot": 1, "type": "uint256"},
            "lib2": {
                "lib1": {"supply": {"slot": 2, "type": "uint256"}},
                "storage_variable": {"slot": 3, "type": "uint256"},
            },
            "counter2": {"slot": 4, "type": "uint256"},
        },
    }

    out = compile_code(code, input_bundle=input_bundle, output_formats=["layout"])
    assert out["layout"] == expected_layout
