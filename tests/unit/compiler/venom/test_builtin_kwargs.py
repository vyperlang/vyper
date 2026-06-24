import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins.misc import _get_bool_kwarg
from vyper.exceptions import CompilerPanic


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


def test_bool_kwarg_uses_reduced_value():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    assert _get_bool_kwarg(call_node, "flag", True) is False


def test_bool_kwarg_rejects_unreduced_value():
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable boolean kwarg: flag"):
        _get_bool_kwarg(call_node, "flag", True)
