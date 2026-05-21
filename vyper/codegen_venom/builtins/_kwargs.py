from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic


_UNSET = object()


@dataclass(frozen=True)
class BuiltinCall:
    node: vy_ast.Call
    ctx: Any

    @property
    def args(self) -> list[vy_ast.VyperNode]:
        return self.node.args

    @property
    def keywords(self) -> list[vy_ast.keyword]:
        return self.node.keywords

    def validate_kwargs(self, allowed_kwarg_names: Iterable[str]) -> None:
        validate_kwargs(self.node, allowed_kwarg_names)

    def get_kwarg_ast_constants(
        self,
        kwarg_defaults: Mapping[str, Any] | Iterable[str],
        error_prefix: str = "unfoldable constant kwarg",
    ) -> dict[str, Any]:
        return get_kwarg_ast_constants(self.node, kwarg_defaults, error_prefix)

    def get_kwarg_values(self, kwarg_defaults: Mapping[str, Any] | Iterable[str]):
        return get_kwarg_values(self.node, self.ctx, kwarg_defaults)

    def lower_pos_args(
        self, arg_nodes: Iterable[vy_ast.VyperNode] | None = None
    ) -> list[Any]:
        from vyper.codegen_venom.expr import Expr

        arg_nodes = self.node.args if arg_nodes is None else arg_nodes
        return [Expr(arg, self.ctx).lower() for arg in arg_nodes]

    def lower_pos_arg_values(
        self, arg_nodes: Iterable[vy_ast.VyperNode] | None = None
    ) -> list[Any]:
        from vyper.codegen_venom.expr import Expr

        arg_nodes = self.node.args if arg_nodes is None else arg_nodes
        return [Expr(arg, self.ctx).lower_value() for arg in arg_nodes]


def _kwarg_names_and_defaults(
    kwarg_defaults: Mapping[str, Any] | Iterable[str],
) -> tuple[set[str], Mapping[str, Any]]:
    if isinstance(kwarg_defaults, Mapping):
        return set(kwarg_defaults), kwarg_defaults
    return set(kwarg_defaults), {}


def _default_value(default):
    if callable(default):
        return default()
    return default


def validate_kwargs(node: vy_ast.Call, allowed_kwarg_names: Iterable[str]) -> None:
    seen = set()
    for kw in node.keywords:
        if kw.arg in seen:  # pragma: nocover
            raise CompilerPanic(f"duplicate kwarg: {kw.arg}", kw)
        seen.add(kw.arg)

    allowed_kwarg_names = set(allowed_kwarg_names)
    for kw in node.keywords:
        if kw.arg not in allowed_kwarg_names:  # pragma: nocover
            raise CompilerPanic(f"unexpected kwarg: {kw.arg}", kw)


def kwarg_is_provided(node: vy_ast.Call, kwarg_name: str) -> bool:
    return any(kw.arg == kwarg_name for kw in node.keywords)


def get_kwarg_ast_constants(
    node: vy_ast.Call,
    kwarg_defaults: Mapping[str, Any] | Iterable[str],
    error_prefix: str = "unfoldable constant kwarg",
) -> dict[str, Any]:
    kwarg_names, defaults = _kwarg_names_and_defaults(kwarg_defaults)
    ret = {}
    for kw in node.keywords:
        if kw.arg not in kwarg_names:
            continue

        kw_node = kw.value.reduced()
        if not isinstance(kw_node, vy_ast.Constant):  # pragma: nocover
            raise CompilerPanic(f"{error_prefix}: {kw.arg}", kw_node)
        ret[kw.arg] = kw_node

    for name, default in defaults.items():
        ret.setdefault(name, default)

    return ret


def get_kwarg_values(
    node: vy_ast.Call,
    ctx,
    kwarg_defaults: Mapping[str, Any] | Iterable[str],
):
    from vyper.codegen_venom.expr import Expr

    kwarg_names, defaults = _kwarg_names_and_defaults(kwarg_defaults)
    ret = {}
    for kw in node.keywords:
        if kw.arg in kwarg_names:
            ret[kw.arg] = Expr(kw.value.reduced(), ctx).lower_value()
    for name, default in defaults.items():
        ret.setdefault(name, _default_value(default))
    return ret


def _literal_value(node: vy_ast.VyperNode) -> Any:
    if isinstance(node, vy_ast.Int):
        return node.value
    if isinstance(node, vy_ast.NameConstant):
        return node.value
    return _UNSET


def get_bool_kwarg(
    kwarg_constants: dict[str, Any],
    kwarg_name: str,
    default: Any = _UNSET,
) -> bool:
    kw_node = kwarg_constants.get(kwarg_name, _UNSET)
    if kw_node is _UNSET:
        if default is _UNSET:  # pragma: nocover
            raise CompilerPanic(f"missing boolean kwarg default: {kwarg_name}")
        return default
    if isinstance(kw_node, bool):
        return kw_node
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value
    if isinstance(kw_node, vy_ast.Int):
        return bool(kw_node.value)
    raise CompilerPanic(f"unfoldable boolean kwarg: {kwarg_name}", kw_node)


def get_literal_kwarg(
    kwarg_constants: dict[str, Any],
    kwarg_name: str,
    default: Any = _UNSET,
):
    kw_node = kwarg_constants.get(kwarg_name, _UNSET)
    if kw_node is _UNSET:
        if default is _UNSET:  # pragma: nocover
            raise CompilerPanic(f"missing literal kwarg default: {kwarg_name}")
        return default
    if kw_node is None or isinstance(kw_node, (bool, int)):
        return kw_node

    value = _literal_value(kw_node)
    if value is not _UNSET:
        return value

    raise CompilerPanic(f"unfoldable literal kwarg: {kwarg_name}", kw_node)
