import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins.abi import _get_bool_kwarg as get_abi_bool_kwarg
from vyper.codegen_venom.builtins.misc import _get_bool_kwarg as get_misc_bool_kwarg
from vyper.exceptions import CompilerPanic


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


@pytest.mark.parametrize("get_bool_kwarg", [get_abi_bool_kwarg, get_misc_bool_kwarg])
def test_bool_kwarg_uses_reduced_value(get_bool_kwarg):
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    assert get_bool_kwarg(call_node, "flag", True) is False


@pytest.mark.parametrize("get_bool_kwarg", [get_abi_bool_kwarg, get_misc_bool_kwarg])
def test_bool_kwarg_rejects_unreduced_value(get_bool_kwarg):
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable boolean kwarg: flag"):
        get_bool_kwarg(call_node, "flag", True)
