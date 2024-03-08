import pytest

from vyper.compiler import compile_code
from vyper.compiler.output import build_abi_output
from vyper.compiler.phases import CompilerData

source_codes = [
    """
x: int128

@deploy
def __init__():
    self.x = 1
    """,
    """
x: int128

@deploy
def __init__():
    pass
    """,
]


@pytest.mark.parametrize("source_code", source_codes)
def test_only_init_function(source_code):
    empty_sig = [
        {"outputs": [], "inputs": [], "stateMutability": "nonpayable", "type": "constructor"}
    ]

    data = CompilerData(source_code)
    assert build_abi_output(data) == empty_sig


def test_default_abi():
    default_code = """
@payable
@external
def __default__():
    pass
    """

    data = CompilerData(default_code)
    assert build_abi_output(data) == [{"stateMutability": "payable", "type": "fallback"}]


def test_method_identifiers():
    code = """
x: public(int128)

@external
def foo(y: uint256) -> Bytes[100]:
    return b"hello"
    """

    out = compile_code(code, output_formats=["method_identifiers"])

    assert out["method_identifiers"] == {"foo(uint256)": "0x2fbebd38", "x()": "0xc55699c"}


def test_struct_abi():
    code = """
struct MyStruct:
    a: address
    b: uint256

@external
@view
def foo(s: MyStruct) -> MyStruct:
    return s
    """

    data = CompilerData(code)
    abi = build_abi_output(data)
    func_abi = abi[0]

    assert func_abi["name"] == "foo"

    expected_output = [
        {
            "type": "tuple",
            "name": "",
            "components": [{"type": "address", "name": "a"}, {"type": "uint256", "name": "b"}],
        }
    ]

    assert func_abi["outputs"] == expected_output

    expected_input = {
        "type": "tuple",
        "name": "s",
        "components": [{"type": "address", "name": "a"}, {"type": "uint256", "name": "b"}],
    }

    assert func_abi["inputs"][0] == expected_input


@pytest.mark.parametrize(
    "type,abi_type", [("DynArray[NestedStruct, 2]", "tuple[]"), ("NestedStruct[2]", "tuple[2]")]
)
def test_nested_struct(type, abi_type):
    code = f"""
struct MyStruct:
    a: address
    b: bytes32

struct NestedStruct:
    t: MyStruct
    foo: uint256

@view
@external
def getStructList() -> {type}:
    return [
        NestedStruct(t=MyStruct(a=msg.sender, b=block.prevhash), foo=1),
        NestedStruct(t=MyStruct(a=msg.sender, b=block.prevhash), foo=2)
    ]
    """

    out = compile_code(code, output_formats=["abi"])

    assert out["abi"] == [
        {
            "inputs": [],
            "name": "getStructList",
            "outputs": [
                {
                    "components": [
                        {
                            "components": [
                                {"name": "a", "type": "address"},
                                {"name": "b", "type": "bytes32"},
                            ],
                            "name": "t",
                            "type": "tuple",
                        },
                        {"name": "foo", "type": "uint256"},
                    ],
                    "name": "",
                    "type": f"{abi_type}",
                }
            ],
            "stateMutability": "view",
            "type": "function",
        }
    ]


@pytest.mark.parametrize(
    "type,abi_type", [("DynArray[DynArray[Foo, 2], 2]", "tuple[][]"), ("Foo[2][2]", "tuple[2][2]")]
)
def test_2d_list_of_struct(type, abi_type):
    code = f"""
struct Foo:
    a: uint256
    b: uint256

@view
@external
def bar(x: {type}):
    pass
    """

    out = compile_code(code, output_formats=["abi"])

    assert out["abi"] == [
        {
            "inputs": [
                {
                    "components": [
                        {"name": "a", "type": "uint256"},
                        {"name": "b", "type": "uint256"},
                    ],
                    "name": "x",
                    "type": f"{abi_type}",
                }
            ],
            "name": "bar",
            "outputs": [],
            "stateMutability": "view",
            "type": "function",
        }
    ]


def test_exports_abi(make_input_bundle):
    lib1 = """
@external
def foo():
    pass

@external
def bar():
    pass
    """

    main = """
import lib1

initializes: lib1

exports: lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])

    # just for clarity -- check bar() is not in the output
    for fn in out["abi"]:
        assert fn["name"] != "bar"

    expected = [
        {
            "inputs": [],
            "name": "foo",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        }
    ]

    assert out["abi"] == expected


def test_exports_variable(make_input_bundle):
    lib1 = """
@external
def foo():
    pass

private_storage_variable: uint256
private_immutable_variable: immutable(uint256)
private_constant_variable: constant(uint256) = 3

public_storage_variable: public(uint256)
public_immutable_variable: public(immutable(uint256))
public_constant_variable: public(constant(uint256)) = 10

@deploy
def __init__(a: uint256, b: uint256):
    public_immutable_variable = a
    private_immutable_variable = b
    """

    main = """
import lib1

initializes: lib1

exports: (
    lib1.foo,
    lib1.public_storage_variable,
    lib1.public_immutable_variable,
    lib1.public_constant_variable,
)

@deploy
def __init__():
    lib1.__init__(5, 6)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = [
        {
            "inputs": [],
            "name": "foo",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "public_storage_variable",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "public_immutable_variable",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "public_constant_variable",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {"inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "constructor"},
    ]

    assert out["abi"] == expected


def test_event_export_from_init(make_input_bundle):
    # test that events get exported when used in init functions
    lib1 = """
event MyEvent:
    pass

@deploy
def __init__():
    log MyEvent()
    """
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"},
            {"inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "constructor"},
        ]
    }

    assert out == expected


def test_event_export_from_function_export(make_input_bundle):
    # test events used in exported functions are exported
    lib1 = """
event MyEvent:
    pass

@external
def foo():
    log MyEvent()
    """
    main = """
import lib1

initializes: lib1

exports: lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"},
            {
                "name": "foo",
                "inputs": [],
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
        ]
    }

    assert out == expected


def test_event_export_unused_function(make_input_bundle):
    # test events in unused functions are not exported
    lib1 = """
event MyEvent:
    pass

@internal
def foo():
    log MyEvent()
    """
    main = """
import lib1
initializes: lib1

# not exported/reachable from selector table
@internal
def do_foo():
    lib1.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {"abi": []}

    assert out == expected


def test_event_export_unused_module(make_input_bundle):
    # test events are exported from functions which are used, even
    # if the module is not marked `uses:`.
    lib1 = """
event MyEvent:
    pass

@internal
def foo():
    log MyEvent()
    """
    main = """
import lib1

@external
def bar():
    lib1.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"},
            {
                "inputs": [],
                "name": "bar",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
        ]
    }

    assert out == expected


def test_event_no_export_implements(make_input_bundle):
    # test events are not exported even if they are in implemented interface
    ifoo = """
event MyEvent:
    pass
    """
    main = """
import ifoo

implements: ifoo
    """
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {"abi": []}

    assert out == expected


def test_event_export_interface(make_input_bundle):
    # test events from interfaces get exported
    ifoo = """
event MyEvent:
    pass

@external
def foo():
    ...
    """
    main = """
import ifoo

@external
def bar():
    log ifoo.MyEvent()
    """
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"},
            {
                "inputs": [],
                "name": "bar",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
        ]
    }
    assert out == expected


def test_event_export_interface_no_use(make_input_bundle):
    # test events from interfaces don't get exported unless used
    ifoo = """
event MyEvent:
    pass

@external
def foo():
    ...
    """
    main = """
import ifoo

@external
def bar():
    extcall ifoo(msg.sender).foo()
    """
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {
                "inputs": [],
                "name": "bar",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]
    }

    assert out == expected


def test_event_export_nested_export_chain(make_input_bundle):
    # test exporting an event from a nested used module
    lib1 = """
event MyEvent:
    pass

@external
def foo():
    log MyEvent()
    """
    lib2 = """
import lib1
exports: lib1.foo
    """
    main = """
import lib2
exports: lib2.lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"},
            {
                "name": "foo",
                "inputs": [],
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
        ]
    }

    assert out == expected


def test_event_export_nested_internal(make_input_bundle):
    # test events are exported from nested internal calls across modules
    lib1 = """
event MyEvent:
    pass

@internal
def foo():
    log MyEvent()
    """
    lib2 = """
import lib1

@internal
def bar():
    lib1.foo()
    """
    main = """
import lib2  # no uses

@external
def baz():
    lib2.bar()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"},
            {
                "name": "baz",
                "inputs": [],
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
        ]
    }

    assert out == expected


def test_event_export_nested_no_uses(make_input_bundle):
    # event is not exported when it's not used
    lib1 = """
event MyEvent:
    pass

counter: uint256

@internal
def foo():
    log MyEvent()

@internal
def update_counter():
    self.counter += 1
    """
    lib2 = """
import lib1
uses: lib1

@internal
def use_lib1():
    lib1.update_counter()
    """
    main = """
import lib1
import lib2

initializes: lib1
initializes: lib2[lib1 := lib1]

@external
def foo():
    lib2.use_lib1()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {
        "abi": [
            {
                "name": "foo",
                "inputs": [],
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]
    }

    assert out == expected
