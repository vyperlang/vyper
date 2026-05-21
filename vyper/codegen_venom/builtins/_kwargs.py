from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic


_UNSET = object()


def get_reduced_kwarg_value(
    node: vy_ast.Call, kwarg_name: str
) -> Optional[vy_ast.VyperNode]:
    for kw in node.keywords:
        if kw.arg == kwarg_name:
            return kw.value.reduced()
    return None


def _literal_value(node: vy_ast.VyperNode) -> Any:
    if isinstance(node, vy_ast.Int):
        return node.value
    if isinstance(node, vy_ast.NameConstant):
        return node.value
    return _UNSET


def get_bool_kwarg(node: vy_ast.Call, kwarg_name: str, default: bool) -> bool:
    kw_node = get_reduced_kwarg_value(node, kwarg_name)
    if kw_node is None:
        return default
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value
    if isinstance(kw_node, vy_ast.Int):
        return bool(kw_node.value)
    raise CompilerPanic(f"unfoldable boolean kwarg: {kwarg_name}", kw_node)


def get_literal_kwarg(node: vy_ast.Call, kwarg_name: str, default):
    kw_node = get_reduced_kwarg_value(node, kwarg_name)
    if kw_node is None:
        return default

    value = _literal_value(kw_node)
    if value is not _UNSET:
        return value

    raise CompilerPanic(f"unfoldable literal kwarg: {kwarg_name}", kw_node)


def lower_kwargs_in_source_order(node: vy_ast.Call, ctx, kwarg_names: Iterable[str]):
    from vyper.codegen_venom.expr import Expr

    kwarg_names = set(kwarg_names)
    ret = {}
    for kw in node.keywords:
        if kw.arg in kwarg_names:
            ret[kw.arg] = Expr(kw.value.reduced(), ctx).lower_value()
    return ret
