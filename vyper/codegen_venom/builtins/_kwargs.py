from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from vyper import ast as vy_ast
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import AddressT, TYPE_T

_UNSET = object()


@dataclass(frozen=True)
class BuiltinCall:
    """Builtin callsite plus the codegen context used to lower it."""

    node: vy_ast.Call
    ctx: Any
    runtime_arg_indices: frozenset[int] | None = None
    runtime_kwarg_names: frozenset[str] = field(default_factory=frozenset)
    materialize_complex_args: bool = False
    _kwarg_nodes: dict[str, vy_ast.VyperNode] | None = field(default=None, init=False, repr=False)
    _lowered_args: tuple[VyperValue | None, ...] = field(default=(), init=False, repr=False)
    _lowered_kwargs: dict[str, VyperValue] = field(default_factory=dict, init=False, repr=False)
    _arg_indices: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        from vyper.codegen_venom.expr import Expr

        kwarg_nodes = collect_kwargs(self.node)
        lowered_args: list[VyperValue | None] = []

        for index, arg in enumerate(self.node.args):
            if not self._should_lower_pos_arg(index, arg):
                lowered_args.append(None)
                continue

            vv = Expr(arg, self.ctx).lower()
            if self.materialize_complex_args and not arg._metadata["type"]._is_prim_word:
                vv = self.ctx.materialize_value(vv, arg._metadata["type"], "builtin arg")
            lowered_args.append(vv)

        lowered_kwargs = {}
        for name, node in kwarg_nodes.items():
            if name in self.runtime_kwarg_names:
                lowered_kwargs[name] = Expr(node.reduced(), self.ctx).lower()

        object.__setattr__(self, "_kwarg_nodes", kwarg_nodes)
        object.__setattr__(self, "_lowered_args", tuple(lowered_args))
        object.__setattr__(self, "_lowered_kwargs", lowered_kwargs)
        object.__setattr__(
            self, "_arg_indices", {id(arg): i for i, arg in enumerate(self.node.args)}
        )

    def _should_lower_pos_arg(self, index: int, arg: vy_ast.VyperNode) -> bool:
        if self.runtime_arg_indices is not None and index not in self.runtime_arg_indices:
            return False

        typ = arg._metadata.get("type")
        if isinstance(typ, TYPE_T):
            return False

        if isinstance(arg, vy_ast.Attribute):
            if arg.attr == "data" and isinstance(arg.value, vy_ast.Name) and arg.value.id == "msg":
                return False
            if arg.attr == "code" and isinstance(arg.value._metadata.get("type"), AddressT):
                return False

        return True

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
        return get_kwarg_values(self._kwargs_dict(), self.ctx, kwarg_defaults, self._lowered_kwargs)

    def lower_pos_args(self, arg_nodes: Iterable[vy_ast.VyperNode] | None = None) -> list[Any]:
        arg_nodes = self.node.args if arg_nodes is None else arg_nodes
        ret = []
        for arg in arg_nodes:
            try:
                index = self._arg_indices[id(arg)]
            except KeyError:  # pragma: nocover
                raise CompilerPanic("requested non-call positional arg")

            vv = self._lowered_args[index]
            if vv is None:  # pragma: nocover
                raise CompilerPanic("requested positional arg was not pre-lowered")
            ret.append(vv)
        return ret

    def lower_pos_arg_values(
        self, arg_nodes: Iterable[vy_ast.VyperNode] | None = None
    ) -> list[Any]:
        return [self.ctx.unwrap(arg) for arg in self.lower_pos_args(arg_nodes)]


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
    lowered_kwargs: Mapping[str, VyperValue] | None = None,
):
    from vyper.codegen_venom.expr import Expr

    kwarg_names, defaults = _kwarg_names_and_defaults(kwarg_defaults)
    ret = {}
    for name, node in kwarg_nodes.items():
        if name in kwarg_names:
            if lowered_kwargs is None:
                ret[name] = Expr(node.reduced(), ctx).lower_value()
            else:
                ret[name] = ctx.unwrap(lowered_kwargs[name])
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
