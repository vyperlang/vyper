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


def test_event_export_from_initialized(make_input_bundle):
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


def test_event_export_uses(make_input_bundle):
    # test exporting an event from a module which is marked `initialized`
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
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {"abi": [{"anonymous": False, "inputs": [], "name": "MyEvent", "type": "event"}]}

    assert out == expected


def test_event_export_no_uses(make_input_bundle):
    # test exporting an event from a module which is not used
    lib1 = """
event MyEvent:
    pass

@internal
def foo():
    log MyEvent()
    """
    main = """
import lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    out = compile_code(main, input_bundle=input_bundle, output_formats=["abi"])
    expected = {"abi": []}

    assert out == expected
