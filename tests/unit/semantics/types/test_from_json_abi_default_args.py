import pytest

from vyper.compiler import CompilerData
from vyper.compiler.output import build_abi_output
from vyper.exceptions import NamespaceCollision
from vyper.semantics.types.module import InterfaceT


def _compile_abi(source: str) -> list[dict]:
    return build_abi_output(CompilerData(source))


def test_default_args_2entries_roundtrip():
    source = """
@external
@view
def foo(a: uint256, b: uint256 = 10) -> uint256:
    return a + b
"""
    abi = _compile_abi(source)
    fn_entries = [e for e in abi if e.get("type") == "function"]
    assert len(fn_entries) == 2

    interface = InterfaceT.from_json_abi("T", abi)
    assert "foo" in interface.functions
    fn = interface.functions["foo"]
    args = list(fn.arguments)
    assert len(args) == 2
    assert args[0].name == "a"
    assert str(args[0].typ) == "uint256"
    assert args[1].name == "b"
    assert str(args[1].typ) == "uint256"


def test_default_args_3entries_roundtrip():
    source = """
@external
@view
def foo(a: uint256, b: uint256 = 1, c: uint256 = 2) -> uint256:
    return a + b + c
"""
    abi = _compile_abi(source)
    fn_entries = [e for e in abi if e.get("type") == "function"]
    assert len(fn_entries) == 3

    interface = InterfaceT.from_json_abi("T", abi)
    assert "foo" in interface.functions
    fn = interface.functions["foo"]
    args = list(fn.arguments)
    assert len(args) == 3
    assert args[0].name == "a"
    assert str(args[0].typ) == "uint256"
    assert args[1].name == "b"
    assert str(args[1].typ) == "uint256"
    assert args[2].name == "c"
    assert str(args[2].typ) == "uint256"


def test_default_args_mixed_types_roundtrip():
    source = """
@external
@view
def baz(a: address, b: bool = True) -> bool:
    return b
"""
    abi = _compile_abi(source)
    fn_entries = [e for e in abi if e.get("type") == "function"]
    assert len(fn_entries) == 2

    interface = InterfaceT.from_json_abi("T", abi)
    fn = interface.functions["baz"]
    args = list(fn.arguments)
    assert len(args) == 2
    assert args[0].name == "a"
    assert str(args[0].typ) == "address"
    assert args[1].name == "b"
    assert str(args[1].typ) == "bool"


def test_default_args_flag_type_roundtrip():
    """Flag types serialize as uint256 in ABI; dedup should treat them
    as compatible and keep the longest overload."""
    source = """
flag MyFlag:
    A
    B
    C

@external
@view
def bar(x: MyFlag, y: uint256 = 0) -> uint256:
    return y
"""
    abi = _compile_abi(source)
    fn_entries = [e for e in abi if e.get("type") == "function"]
    assert len(fn_entries) == 2

    interface = InterfaceT.from_json_abi("T", abi)
    fn = interface.functions["bar"]
    args = list(fn.arguments)
    assert len(args) == 2
    assert args[0].name == "x"
    assert str(args[0].typ) == "uint256"
    assert args[1].name == "y"
    assert str(args[1].typ) == "uint256"


def test_no_default_args_unchanged():
    abi = [
        {
            "type": "function",
            "name": "bar",
            "stateMutability": "view",
            "inputs": [{"name": "a", "type": "uint256"}],
            "outputs": [{"name": "", "type": "uint256"}],
        }
    ]
    interface = InterfaceT.from_json_abi("T", abi)
    assert "bar" in interface.functions
    fn = interface.functions["bar"]
    args = list(fn.arguments)
    assert len(args) == 1
    assert args[0].name == "a"
    assert str(args[0].typ) == "uint256"


def test_manual_ordering_keeps_longest_overload():
    abi = [
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [
                {"name": "a", "type": "uint256"},
                {"name": "b", "type": "uint256"},
                {"name": "c", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "uint256"}],
        },
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [{"name": "a", "type": "uint256"}],
            "outputs": [{"name": "", "type": "uint256"}],
        },
    ]
    interface = InterfaceT.from_json_abi("T", abi)
    fn = interface.functions["foo"]
    args = list(fn.arguments)
    assert len(args) == 3
    assert args[0].name == "a"
    assert args[1].name == "b"
    assert args[2].name == "c"


def test_incompatible_overload_raises():
    abi = [
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [{"name": "a", "type": "uint256"}],
            "outputs": [{"name": "", "type": "uint256"}],
        },
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [{"name": "a", "type": "address"}],
            "outputs": [{"name": "", "type": "uint256"}],
        },
    ]
    with pytest.raises(NamespaceCollision, match="incompatible input types"):
        InterfaceT.from_json_abi("T", abi)


def test_incompatible_overload_at_later_position_raises():
    abi = [
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [
                {"name": "a", "type": "uint256"},
                {"name": "b", "type": "uint256"},
            ],
            "outputs": [{"name": "", "type": "uint256"}],
        },
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [
                {"name": "a", "type": "uint256"},
                {"name": "b", "type": "address"},
            ],
            "outputs": [{"name": "", "type": "uint256"}],
        },
    ]
    with pytest.raises(NamespaceCollision, match="incompatible input types"):
        InterfaceT.from_json_abi("T", abi)


def test_decimal_vs_int168_rejected_despite_same_raw_type():
    # Vyper emits both `decimal` and `int168` with `"type": "int168"` in
    # the ABI, distinguished only by `internalType`. Ensure the dedup
    # compares parsed argument types rather than the raw `type` string,
    # so these are treated as incompatible.
    abi = [
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [{"name": "a", "type": "int168", "internalType": "decimal"}],
            "outputs": [{"name": "", "type": "int168", "internalType": "decimal"}],
        },
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "view",
            "inputs": [{"name": "a", "type": "int168"}],
            "outputs": [{"name": "", "type": "int168"}],
        },
    ]
    with pytest.raises(NamespaceCollision, match="incompatible input types"):
        InterfaceT.from_json_abi("T", abi)
