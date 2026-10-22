import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._kwargs import get_bool_kwarg, get_kwarg_value
from vyper.compiler import compile_code
from vyper.exceptions import CompilerPanic, TypeMismatch


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


def test_kwarg_value_returns_node_or_default():
    call_node = _call_node("foo(flag=FLAG)")

    assert get_kwarg_value(call_node, "flag") is call_node.keywords[0].value
    assert get_kwarg_value(call_node, "other") is None
    assert get_kwarg_value(call_node, "other", 3) == 3


def test_bool_kwarg_returns_default_when_absent():
    call_node = _call_node("foo(other=FLAG)")

    assert get_bool_kwarg(call_node, "flag", True) is True
    assert get_bool_kwarg(call_node, "flag", False) is False


@pytest.mark.parametrize("value", [True, False])
def test_bool_kwarg_uses_reduced_value(value):
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=value))

    assert get_bool_kwarg(call_node, "flag", not value) is value


def test_bool_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable boolean kwarg: flag"):
        get_bool_kwarg(call_node, "flag", True)


def test_bool_kwarg_rejects_int_value():
    call_node = _call_node("foo(flag=1)")

    with pytest.raises(CompilerPanic, match="unfoldable boolean kwarg: flag"):
        get_bool_kwarg(call_node, "flag", False)


# the frontend never lets a non-bool reach `get_bool_kwarg`: every builtin
# that uses it declares the kwarg as a literal `BoolT`.
@pytest.mark.parametrize(
    "call",
    [
        "abi_encode(x, ensure_tuple={})",
        "abi_decode(abi_encode(x), uint256, unwrap_tuple={})",
        "print(x, hardhat_compat={})",
    ],
)
@pytest.mark.parametrize("value,decl", [("1", ""), ("0", ""), ("N", "N: constant(uint256) = 1")])
def test_bool_kwarg_builtins_reject_int(call, value, decl):
    code = f"""
{decl}

@external
def foo(x: uint256):
    y: Bytes[64] = b""
    {"y = " if call.startswith("abi_encode") else ""}{call.format(value)}
    """
    with pytest.raises(TypeMismatch):
        compile_code(code)
