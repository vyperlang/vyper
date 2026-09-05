"""Prepare builtin inputs once, in source order, before handler dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vyper import ast as vy_ast
from vyper.builtins._signatures import ContextDefault
from vyper.codegen_venom.buffer import Buffer
from vyper.codegen_venom.eval_order import expression_can_mutate_memory_or_storage
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import TYPE_T, AddressT, VyperType
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def is_msg_data(node: vy_ast.VyperNode) -> bool:
    return (
        isinstance(node, vy_ast.Attribute)
        and isinstance(node.value, vy_ast.Name)
        and node.value.id == "msg"
        and node.attr == "data"
    )


def is_slice_view(node: vy_ast.VyperNode) -> bool:
    if is_msg_data(node):
        return True
    return (
        isinstance(node, vy_ast.Attribute)
        and node.attr == "code"
        and (
            isinstance(node.value, vy_ast.Name)
            and node.value.id == "self"
            or isinstance(node.value._metadata.get("type"), AddressT)
        )
    )


class BuiltinCall:
    """An analyzed call with eager words and stable memory inputs.

    Only this constructor lowers runtime input expressions. Its accessors
    return prepared values without emitting loads or copies. Type expressions and
    literal-only inputs remain AST metadata; len, raw_log and raw slice sources
    have explicit preparation rules because they do not consume ordinary values.
    """

    def __init__(self, node: vy_ast.Call, ctx: VenomCodegenContext):
        # Local import avoids expr -> builtin handlers -> expr.
        from vyper.codegen_venom.expr import Expr

        self.node = node
        self.ctx = ctx
        self.func_t = node.func._metadata["type"]
        self._values: dict[vy_ast.VyperNode, VyperValue] = {}
        self._kwargs: dict[str, IROperand] = {}
        self._literals: dict[str, Any] = {}
        self.provided_kwargs = {kw.arg for kw in node.keywords}
        self.length: IROperand | None = None
        nodes = []

        for i, arg in enumerate(node.args):
            if isinstance(arg._metadata["type"], TYPE_T):
                continue
            if self.func_t._id == "as_wei_value" and i == 1:
                continue  # denomination is a compile-time literal
            if self.func_t._id == "len":
                if is_msg_data(arg):
                    self.length = ctx.builder.calldatasize()
                else:
                    value = Expr(arg, ctx).lower()
                    assert value.location is not None
                    self.length = ctx.load_word(value.operand, value.location)
                continue
            if self.func_t._id == "raw_log" and i == 0:
                topics = arg.reduced()
                assert isinstance(topics, vy_ast.List)
                nodes.extend(topics.elements)
                continue
            if self.func_t._id == "slice" and i == 0 and is_slice_view(arg):
                assert isinstance(arg, vy_ast.Attribute)
                if not is_msg_data(arg) and not (
                    isinstance(arg.value, vy_ast.Name) and arg.value.id == "self"
                ):
                    nodes.append(arg.value)  # external code address precedes slice bounds
                continue
            if self.func_t._id == "raw_call" and i == 1 and is_msg_data(arg):
                continue  # immutable calldata is copied by the handler
            nodes.append(arg)

        for kw in node.keywords:
            settings = self.func_t._kwargs[kw.arg]
            if isinstance(kw.value._metadata["type"], TYPE_T):
                continue
            if settings.require_literal:
                folded = kw.value.reduced()
                if not isinstance(folded, vy_ast.Constant):  # pragma: nocover
                    raise CompilerPanic(f"unfoldable kwarg: {kw.arg}", kw)
                self._literals[kw.arg] = folded.value
            else:
                nodes.append(kw.value)

        # A single suffix scan determines which borrowed memory values need
        # snapshots before later expressions can mutate their aliases.
        snapshots = [False] * len(nodes)
        later_mutates = False
        for i in range(len(nodes) - 1, -1, -1):
            snapshots[i] = later_mutates
            later_mutates |= expression_can_mutate_memory_or_storage(nodes[i])

        for arg, snapshot in zip(nodes, snapshots):
            value = Expr(arg, ctx).lower()
            if value.typ._is_prim_word or (snapshot and value.location is DataLocation.MEMORY):
                value = ctx.snapshot_value_for_delayed_use(value, copy_composites=snapshot)
            if value.location is not None and value.location in (
                DataLocation.STORAGE,
                DataLocation.TRANSIENT,
                DataLocation.IMMUTABLES,
            ):
                # unwrap copies these composites directly into one memory buffer.
                ptr = ctx.unwrap(value)
                assert isinstance(ptr, IRVariable)
                value = VyperValue.from_ptr(
                    Buffer(ptr, value.typ.memory_bytes_required).base_ptr(), value.typ
                )
            if (
                value.location is not None and value.location is not DataLocation.MEMORY
            ):  # pragma: nocover
                raise CompilerPanic("builtin input must be decoded before preparation", arg)
            self._values[arg] = value

        # Explicit runtime kwargs were evaluated in source order above. Missing
        # defaults follow them, and their values come from the semantic signature.
        for kw in node.keywords:
            if kw.value in self._values:
                self._kwargs[kw.arg] = self.operand(kw.value)
        for name, settings in self.func_t._kwargs.items():
            if name in self.provided_kwargs or isinstance(settings.default, VyperType):
                continue
            if settings.require_literal:
                self._literals[name] = settings.default
            elif settings.default is ContextDefault.GAS:
                self._kwargs[name] = ctx.builder.gas()
            elif type(settings.default) is int:
                self._kwargs[name] = IRLiteral(settings.default)
            else:  # pragma: nocover
                raise CompilerPanic(f"unsupported runtime default: {name}")

    def value(self, node: vy_ast.VyperNode) -> VyperValue:
        return self._values[node]

    def operand(self, node: vy_ast.VyperNode) -> IROperand:
        return self.value(node).operand

    def kwarg(self, name: str) -> IROperand:
        return self._kwargs[name]

    def literal(self, name: str) -> Any:
        return self._literals[name]

    def was_provided(self, name: str) -> bool:
        return name in self.provided_kwargs
