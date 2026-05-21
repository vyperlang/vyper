import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._kwargs import (
    get_bool_kwarg,
    get_kwarg_ast_constants,
    get_literal_kwarg,
    kwarg_is_provided,
)
from vyper.exceptions import CompilerPanic


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


def test_kwarg_ast_constants_return_folded_nodes():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    constants = get_kwarg_ast_constants(
        call_node, ("flag",), allowed_kwarg_names=("flag",)
    )

    assert constants["flag"].value is False


def test_kwarg_ast_constants_reject_unfolded_values():
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: flag"):
        get_kwarg_ast_constants(call_node, ("flag",))


def test_kwarg_helpers_reject_unexpected_kwargs():
    call_node = _call_node("foo(flag=False)")

    with pytest.raises(CompilerPanic, match="unexpected kwarg: flag"):
        kwarg_is_provided(call_node, "flag", allowed_kwarg_names=("other",))


def test_kwarg_helpers_reject_duplicate_kwargs():
    call_node = _call_node("foo(flag=False, flag=True)")

    with pytest.raises(CompilerPanic, match="duplicate kwarg: flag"):
        get_kwarg_ast_constants(call_node, ("flag",))


def test_kwarg_is_provided():
    call_node = _call_node("foo(flag=False)")

    assert kwarg_is_provided(call_node, "flag", allowed_kwarg_names=("flag",)) is True
    assert kwarg_is_provided(call_node, "other", allowed_kwarg_names=("flag",)) is False


def test_bool_kwarg_uses_reduced_value():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))
    constants = get_kwarg_ast_constants(call_node, ("flag",), allowed_kwarg_names=("flag",))

    assert get_bool_kwarg(constants, "flag", True) is False


def test_bool_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: flag"):
        get_kwarg_ast_constants(call_node, ("flag",))


def test_literal_kwarg_uses_reduced_value():
    call_node = _call_node("foo(revert_on_failure=REVERT)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))
    constants = get_kwarg_ast_constants(
        call_node, ("revert_on_failure",), allowed_kwarg_names=("revert_on_failure",)
    )

    assert get_literal_kwarg(constants, "revert_on_failure", True) is False


def test_literal_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(revert_on_failure=REVERT)")

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: revert_on_failure"):
        get_kwarg_ast_constants(call_node, ("revert_on_failure",))
