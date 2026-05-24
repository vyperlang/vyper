from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic

_UNSET = object()


@dataclass(frozen=True)
class BuiltinCall:
    """Builtin callsite plus the codegen context used to lower it."""

    node: vy_ast.Call
    ctx: Any
    _kwarg_nodes: dict[str, vy_ast.VyperNode] | None = field(default=None, init=False, repr=False)

    @property
    def args(self) -> list[vy_ast.VyperNode]:
        return self.node.args

    @property
    def keywords(self) -> list[vy_ast.keyword]:
        return self.node.keywords

    def validate_kwargs(self, allowed_kwarg_names: Iterable[str]) -> dict[str, vy_ast.VyperNode]:
        kwarg_nodes = validate_kwargs(self.node, allowed_kwarg_names)
        object.__setattr__(self, "_kwarg_nodes", kwarg_nodes)
        return kwarg_nodes

    def _kwargs_dict(self) -> dict[str, vy_ast.VyperNode]:
        if self._kwarg_nodes is None:
            return collect_kwargs(self.node)
        return self._kwarg_nodes

    def kwarg_is_provided(self, kwarg_name: str) -> bool:
        return kwarg_is_provided(self._kwargs_dict(), kwarg_name)

    def get_kwarg_ast_constants(
        self,
        kwarg_defaults: Mapping[str, Any] | Iterable[str],
        error_prefix: str = "unfoldable constant kwarg",
    ) -> dict[str, Any]:
        return get_kwarg_ast_constants(self._kwargs_dict(), kwarg_defaults, error_prefix)

    def get_kwarg_values(self, kwarg_defaults: Mapping[str, Any] | Iterable[str]):
        return get_kwarg_values(self._kwargs_dict(), self.ctx, kwarg_defaults)

    def lower_pos_args(self, arg_nodes: Iterable[vy_ast.VyperNode] | None = None) -> list[Any]:
        from vyper.codegen_venom.expr import Expr

        arg_nodes = self.node.args if arg_nodes is None else arg_nodes
        # Positional args are yielded in AST/source order. Each caller should
        # route every runtime arg through exactly one lowering helper.
        return [Expr(arg, self.ctx).lower() for arg in arg_nodes]

    def lower_pos_arg_values(
        self, arg_nodes: Iterable[vy_ast.VyperNode] | None = None
    ) -> list[Any]:
        from vyper.codegen_venom.expr import Expr

        arg_nodes = self.node.args if arg_nodes is None else arg_nodes
        # Positional args are yielded in AST/source order. Each caller should
        # route every runtime arg through exactly one lowering helper.
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


def _allowed_kwarg_names(allowed_kwarg_names: Iterable[str]) -> set[str]:
    ret = set()
    for name in allowed_kwarg_names:
        if name in ret:  # pragma: nocover
            raise CompilerPanic(f"duplicate allowed kwarg: {name}")
        ret.add(name)
    return ret


def collect_kwargs(node: vy_ast.Call) -> dict[str, vy_ast.VyperNode]:
    ret = {}
    for kw in node.keywords:
        if kw.arg in ret:  # pragma: nocover
            raise CompilerPanic(f"duplicate kwarg: {kw.arg}", kw)
        ret[kw.arg] = kw.value
    return ret


def validate_kwargs(
    node: vy_ast.Call, allowed_kwarg_names: Iterable[str]
) -> dict[str, vy_ast.VyperNode]:
    allowed_kwarg_names = _allowed_kwarg_names(allowed_kwarg_names)
    ret = {}
    for kw in node.keywords:
        if kw.arg in ret:  # pragma: nocover
            raise CompilerPanic(f"duplicate kwarg: {kw.arg}", kw)
        if kw.arg not in allowed_kwarg_names:  # pragma: nocover
            raise CompilerPanic(f"unexpected kwarg: {kw.arg}", kw)
        ret[kw.arg] = kw.value
    return ret


def kwarg_is_provided(kwarg_nodes: Mapping[str, vy_ast.VyperNode], kwarg_name: str) -> bool:
    return kwarg_name in kwarg_nodes


def get_kwarg_ast_constants(
    kwarg_nodes: Mapping[str, vy_ast.VyperNode],
    kwarg_defaults: Mapping[str, Any] | Iterable[str],
    error_prefix: str = "unfoldable constant kwarg",
) -> dict[str, Any]:
    kwarg_names, defaults = _kwarg_names_and_defaults(kwarg_defaults)
    ret = {}
    for name, node in kwarg_nodes.items():
        if name not in kwarg_names:
            continue

        kw_node = node.reduced()
        if not isinstance(kw_node, vy_ast.Constant):  # pragma: nocover
            raise CompilerPanic(f"{error_prefix}: {name}", kw_node)
        ret[name] = kw_node

    for name, default in defaults.items():
        ret.setdefault(name, default)

    return ret


def get_kwarg_values(
    kwarg_nodes: Mapping[str, vy_ast.VyperNode],
    ctx,
    kwarg_defaults: Mapping[str, Any] | Iterable[str],
):
    from vyper.codegen_venom.expr import Expr

    kwarg_names, defaults = _kwarg_names_and_defaults(kwarg_defaults)
    ret = {}
    # `kwarg_nodes` is produced by walking node.keywords in source order.
    # Do not iterate over `kwarg_names` here: lowering emits code, so every
    # explicit runtime kwarg must be lowered once, in the user's keyword order.
    for name, node in kwarg_nodes.items():
        if name in kwarg_names:
            ret[name] = Expr(node.reduced(), ctx).lower_value()
    for name, default in defaults.items():
        ret.setdefault(name, _default_value(default))
    return ret


def get_bool_kwarg(kwarg_constants: dict[str, Any], kwarg_name: str, default: Any = _UNSET) -> bool:
    kw_node = kwarg_constants.get(kwarg_name, _UNSET)
    if kw_node is _UNSET:
        if default is _UNSET:  # pragma: nocover
            raise CompilerPanic(f"missing boolean kwarg default: {kwarg_name}")
        return default
    if isinstance(kw_node, bool):
        return kw_node
    if isinstance(kw_node, vy_ast.Constant):
        value = kw_node.value
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
    raise CompilerPanic(f"unfoldable boolean kwarg: {kwarg_name}", kw_node)


def get_literal_kwarg(kwarg_constants: dict[str, Any], kwarg_name: str, default: Any = _UNSET):
    kw_node = kwarg_constants.get(kwarg_name, _UNSET)
    if kw_node is _UNSET:
        if default is _UNSET:  # pragma: nocover
            raise CompilerPanic(f"missing literal kwarg default: {kwarg_name}")
        return default
    if kw_node is None or isinstance(kw_node, (bool, int)):
        return kw_node
    if isinstance(kw_node, vy_ast.Constant):
        return kw_node.value

    raise CompilerPanic(f"unfoldable literal kwarg: {kwarg_name}", kw_node)
