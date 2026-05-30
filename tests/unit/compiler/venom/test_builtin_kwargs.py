import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._kwargs import (
    get_bool_kwarg,
    get_kwarg_ast_constants,
    get_kwarg_values,
    get_literal_kwarg,
    kwarg_is_provided,
    validate_kwargs,
)
from vyper.exceptions import CompilerPanic


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


def test_kwarg_ast_constants_return_folded_nodes():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))
    kwarg_nodes = validate_kwargs(call_node, ("flag",))

    constants = get_kwarg_ast_constants(kwarg_nodes, ("flag",))

    assert constants["flag"].value is False


def test_kwarg_ast_constants_reject_unfolded_values():
    call_node = _call_node("foo(flag=FLAG)")
    kwarg_nodes = validate_kwargs(call_node, ("flag",))

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: flag"):
        get_kwarg_ast_constants(kwarg_nodes, ("flag",))


def test_kwarg_helpers_reject_unexpected_kwargs():
    call_node = _call_node("foo(flag=False)")

    with pytest.raises(CompilerPanic, match="unexpected kwarg: flag"):
        validate_kwargs(call_node, ("other",))


def test_kwarg_helpers_reject_duplicate_kwargs():
    call_node = _call_node("foo(flag=False, flag=True)")

    with pytest.raises(CompilerPanic, match="duplicate kwarg: flag"):
        validate_kwargs(call_node, ("flag",))


def test_kwarg_helpers_reject_duplicate_allowed_kwargs():
    call_node = _call_node("foo(flag=False)")

    with pytest.raises(CompilerPanic, match="duplicate allowed kwarg: flag"):
        validate_kwargs(call_node, ("flag", "flag"))


def test_kwarg_is_provided():
    call_node = _call_node("foo(flag=False)")
    kwarg_nodes = validate_kwargs(call_node, ("flag",))

    assert kwarg_is_provided(kwarg_nodes, "flag") is True
    assert kwarg_is_provided(kwarg_nodes, "other") is False


def test_bool_kwarg_uses_reduced_value():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))
    kwarg_nodes = validate_kwargs(call_node, ("flag",))
    constants = get_kwarg_ast_constants(kwarg_nodes, ("flag",))

    assert get_bool_kwarg(constants, "flag", True) is False


def test_kwarg_constants_fill_defaults():
    call_node = _call_node("foo(flag=False)")
    kwarg_nodes = validate_kwargs(call_node, ("flag",))

    constants = get_kwarg_ast_constants(kwarg_nodes, {"flag": True, "limit": 3, "salt": None})

    assert get_bool_kwarg(constants, "flag") is False
    assert get_literal_kwarg(constants, "limit") == 3
    assert get_literal_kwarg(constants, "salt") is None


def test_kwarg_values_fill_late_defaults():
    call_node = _call_node("foo()")
    kwarg_nodes = validate_kwargs(call_node, ())

    values = get_kwarg_values(kwarg_nodes, object(), {"gas": lambda: "gas-left", "value": 0})

    assert values == {"gas": "gas-left", "value": 0}


def test_bool_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(flag=FLAG)")
    kwarg_nodes = validate_kwargs(call_node, ("flag",))

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: flag"):
        get_kwarg_ast_constants(kwarg_nodes, ("flag",))


def test_literal_kwarg_uses_reduced_value():
    call_node = _call_node("foo(revert_on_failure=REVERT)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))
    kwarg_nodes = validate_kwargs(call_node, ("revert_on_failure",))
    constants = get_kwarg_ast_constants(kwarg_nodes, ("revert_on_failure",))

    assert get_literal_kwarg(constants, "revert_on_failure", True) is False


def test_literal_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(revert_on_failure=REVERT)")
    kwarg_nodes = validate_kwargs(call_node, ("revert_on_failure",))

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: revert_on_failure"):
        get_kwarg_ast_constants(kwarg_nodes, ("revert_on_failure",))
