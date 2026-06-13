import pytest

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._call import BuiltinCall, CallsiteSpec
from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRLiteral


def _call_node(source):
    return vy_ast.parse_to_ast(source).body[0].value


def _spec(constant_kwargs=None, runtime_kwargs=None, type_kwargs=(), handler_args=()):
    return CallsiteSpec(constant_kwargs or {}, runtime_kwargs or {}, type_kwargs, handler_args)


def test_constant_kwargs_fold_to_python_values():
    call_node = _call_node("foo(flag=FLAG)")
    call_node.keywords[0].value._set_folded_value(vy_ast.NameConstant(value=False))

    call = BuiltinCall(call_node, ctx=None, spec=_spec(constant_kwargs={"flag": True}))

    assert call.kwarg_constants == {"flag": False}


def test_constant_kwargs_fill_defaults():
    call_node = _call_node("foo(flag=False)")

    spec = _spec(constant_kwargs={"flag": True, "limit": 3, "salt": None})
    call = BuiltinCall(call_node, ctx=None, spec=spec)

    assert call.kwarg_constants == {"flag": False, "limit": 3, "salt": None}


def test_constant_kwargs_reject_unfolded_values():
    call_node = _call_node("foo(flag=FLAG)")

    with pytest.raises(CompilerPanic, match="unfoldable constant kwarg: flag"):
        BuiltinCall(call_node, ctx=None, spec=_spec(constant_kwargs={"flag": True}))


def test_unexpected_kwarg_rejected():
    call_node = _call_node("foo(flag=False)")

    with pytest.raises(CompilerPanic, match="unexpected kwarg: flag"):
        BuiltinCall(call_node, ctx=None, spec=_spec(constant_kwargs={"other": None}))


def test_kwarg_declared_with_more_than_one_kind_rejected():
    with pytest.raises(AssertionError, match="kwarg declared with more than one kind"):
        _spec(constant_kwargs={"flag": True}, runtime_kwargs={"flag": 0})


def test_provided_kwargs():
    call_node = _call_node("foo(flag=False)")

    call = BuiltinCall(call_node, ctx=None, spec=_spec(constant_kwargs={"flag": True}))

    assert "flag" in call.provided_kwargs
    assert "other" not in call.provided_kwargs


def test_runtime_kwarg_defaults():
    call_node = _call_node("foo()")

    spec = _spec(runtime_kwargs={"gas": lambda ctx: "gas-left", "value": 0, "salt": None})
    call = BuiltinCall(call_node, ctx=None, spec=spec)

    # callables are invoked with the codegen context, ints become
    # IRLiterals, None means "no default" and stays None
    assert call.kwarg_values == {"gas": "gas-left", "value": IRLiteral(0), "salt": None}
