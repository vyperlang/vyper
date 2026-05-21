import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._kwargs import (
    get_bool_kwarg,
    get_literal_kwarg,
    get_maybe_literal_kwarg,
    get_reduced_kwarg_value,
)
from vyper.exceptions import CompilerPanic


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


def test_reduced_kwarg_value_returns_folded_node():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    assert get_reduced_kwarg_value(call_node, "flag").value is False


def test_bool_kwarg_uses_reduced_value():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    assert get_bool_kwarg(call_node, "flag", True) is False


def test_bool_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable boolean kwarg: flag"):
        get_bool_kwarg(call_node, "flag", True)


def test_literal_kwarg_uses_reduced_value():
    call_node = _call_node("foo(revert_on_failure=REVERT)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    assert get_literal_kwarg(call_node, "revert_on_failure", True) is False


def test_literal_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(revert_on_failure=REVERT)")

    with pytest.raises(CompilerPanic, match="unfoldable literal kwarg: revert_on_failure"):
        get_literal_kwarg(call_node, "revert_on_failure", True)


def test_maybe_literal_kwarg_allows_runtime_value():
    call_node = _call_node("foo(code_offset=runtime_value)")

    value, is_literal = get_maybe_literal_kwarg(call_node, "code_offset", 3)

    assert value is None
    assert is_literal is False
