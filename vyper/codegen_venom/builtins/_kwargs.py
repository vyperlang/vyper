from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic


_UNSET = object()


def _validate_allowed_kwargs(
    node: vy_ast.Call, allowed_kwarg_names: Iterable[str] | None
) -> None:
    if allowed_kwarg_names is None:
        return

    allowed_kwarg_names = set(allowed_kwarg_names)
    for kw in node.keywords:
        if kw.arg not in allowed_kwarg_names:  # pragma: nocover
            raise CompilerPanic(f"unexpected kwarg: {kw.arg}", kw)


def kwarg_is_provided(
    node: vy_ast.Call, kwarg_name: str, allowed_kwarg_names: Iterable[str] | None = None
) -> bool:
    _validate_allowed_kwargs(node, allowed_kwarg_names)
    return any(kw.arg == kwarg_name for kw in node.keywords)


def get_kwarg_ast_constants(
    node: vy_ast.Call,
    kwarg_names: Iterable[str],
    allowed_kwarg_names: Iterable[str] | None = None,
    error_prefix: str = "unfoldable constant kwarg",
) -> dict[str, vy_ast.Constant]:
    _validate_allowed_kwargs(node, allowed_kwarg_names)
    kwarg_names = set(kwarg_names)
    ret = {}
    for kw in node.keywords:
        if kw.arg not in kwarg_names:
            continue

        kw_node = kw.value.reduced()
        if not isinstance(kw_node, vy_ast.Constant):  # pragma: nocover
            raise CompilerPanic(f"{error_prefix}: {kw.arg}", kw_node)
        ret[kw.arg] = kw_node

    return ret


def get_kwarg_values(
    node: vy_ast.Call,
    ctx,
    kwarg_names: Iterable[str],
    allowed_kwarg_names: Iterable[str] | None = None,
):
    from vyper.codegen_venom.expr import Expr

    _validate_allowed_kwargs(node, allowed_kwarg_names)
    kwarg_names = set(kwarg_names)
    ret = {}
    for kw in node.keywords:
        if kw.arg in kwarg_names:
            ret[kw.arg] = Expr(kw.value.reduced(), ctx).lower_value()
    return ret


def _literal_value(node: vy_ast.VyperNode) -> Any:
    if isinstance(node, vy_ast.Int):
        return node.value
    if isinstance(node, vy_ast.NameConstant):
        return node.value
    return _UNSET


def get_bool_kwarg(
    node: vy_ast.Call,
    kwarg_name: str,
    default: bool,
    allowed_kwarg_names: Iterable[str] | None = None,
) -> bool:
    kw_node = get_kwarg_ast_constants(
        node,
        (kwarg_name,),
        allowed_kwarg_names,
        error_prefix="unfoldable boolean kwarg",
    ).get(kwarg_name)
    if kw_node is None:
        return default
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value
    if isinstance(kw_node, vy_ast.Int):
        return bool(kw_node.value)
    raise CompilerPanic(f"unfoldable boolean kwarg: {kwarg_name}", kw_node)


def get_literal_kwarg(
    node: vy_ast.Call,
    kwarg_name: str,
    default,
    allowed_kwarg_names: Iterable[str] | None = None,
):
    kw_node = get_kwarg_ast_constants(
        node,
        (kwarg_name,),
        allowed_kwarg_names,
        error_prefix="unfoldable literal kwarg",
    ).get(kwarg_name)
    if kw_node is None:
        return default

    value = _literal_value(kw_node)
    if value is not _UNSET:
        return value

    raise CompilerPanic(f"unfoldable literal kwarg: {kwarg_name}", kw_node)
