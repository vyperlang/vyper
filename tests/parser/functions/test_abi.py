import pytest

from vyper.compiler import compile_code
from vyper.compiler.output import build_abi_output
from vyper.compiler.phases import CompilerData

source_codes = [
    """
x: int128

@external
def __init__():
    self.x = 1
    """,
    """
x: int128

@external
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

    out = compile_code(code, output_formats=["method_identifiers"],)

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
