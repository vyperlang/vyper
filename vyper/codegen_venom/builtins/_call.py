"""Semantic binding and source-ordered preparation for Venom builtins."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Union

from vyper import ast as vy_ast
from vyper.builtins._signatures import ContextDefault
from vyper.codegen_venom.call_args import (
    VALUE,
    ArgPolicy,
    DataSourcePolicy,
    DataView,
    DataViewKind,
    FoldedArgument,
    FoldedPolicy,
    LengthPolicy,
    PreparedArg,
    PreparedDataSource,
    PreparedList,
    TypeArgument,
    ValueListPolicy,
    ValuePolicy,
    classify_data_view,
)
from vyper.codegen_venom.value import PreparedValue, VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import TYPE_T, VyperType
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.builtins._signatures import BuiltinFunctionT
    from vyper.codegen_venom.context import VenomCodegenContext

HandlerResult = Union[IROperand, VyperValue]
BuiltinHandler = Callable[["PreparedBuiltinCall"], HandlerResult]
ArgKey = Union[int, str]


@dataclass(frozen=True)
class BuiltinSignature:
    """The semantic builtin signature bound to one annotated call."""

    func_t: "BuiltinFunctionT"
    arg_types: tuple[Any, ...]
    arg_names: tuple[str, ...]
    declared_arg_names: tuple[str, ...]
    kwarg_settings: Mapping[str, Any]
    return_type: VyperType

    @classmethod
    def from_call(cls, func_t: "BuiltinFunctionT", node: vy_ast.Call) -> "BuiltinSignature":
        # Semantic analysis has already resolved every source argument,
        # including user-defined type expressions which cannot be reparsed
        # here without the original namespace.
        arg_types = tuple(arg._metadata["type"] for arg in node.args)

        declared_names = tuple(name for name, _ in func_t._inputs)
        arg_names = tuple(
            declared_names[i] if i < len(declared_names) else f"arg{i}"
            for i in range(len(node.args))
        )
        return cls(
            func_t=func_t,
            arg_types=arg_types,
            arg_names=arg_names,
            declared_arg_names=declared_names,
            kwarg_settings=MappingProxyType(dict(func_t._kwargs)),
            return_type=node._metadata["type"],
        )


@dataclass(frozen=True)
class BuiltinLowerer:
    """A handler plus backend representation policies for exceptional args."""

    handler: BuiltinHandler
    arg_policies: Mapping[str, ArgPolicy] = field(default_factory=dict)
    vararg_policy: ArgPolicy = VALUE

    def __post_init__(self):
        object.__setattr__(self, "arg_policies", MappingProxyType(dict(self.arg_policies)))

    def validate(self, signature: BuiltinSignature) -> None:
        unknown = set(self.arg_policies) - set(signature.declared_arg_names)
        if unknown:  # pragma: nocover
            names = ", ".join(sorted(unknown))
            raise CompilerPanic(f"{signature.func_t._id}: policies for unknown args: {names}")

    def policy_for_arg(self, signature: BuiltinSignature, index: int) -> ArgPolicy:
        if index < len(signature.declared_arg_names):
            return self.arg_policies.get(signature.arg_names[index], VALUE)
        return self.vararg_policy


@dataclass(frozen=True)
class _ArgDestination:
    index: int


@dataclass(frozen=True)
class _LengthDestination:
    index: int


@dataclass(frozen=True)
class _ListDestination:
    index: int
    element_index: int


@dataclass(frozen=True)
class _ViewDestination:
    index: int
    kind: DataViewKind
    as_length: bool = False


@dataclass(frozen=True)
class _KwargDestination:
    name: str


_Destination = Union[
    _ArgDestination, _LengthDestination, _ListDestination, _ViewDestination, _KwargDestination
]


@dataclass(frozen=True)
class _ValueStep:
    node: vy_ast.VyperNode
    destination: _Destination
    reduce_node: bool = False
    snapshot_memory: bool = False


@dataclass(frozen=True)
class _LengthViewStep:
    index: int
    kind: DataViewKind


@dataclass(frozen=True)
class _DefaultStep:
    name: str
    settings: Any


_EvaluationStep = Union[_ValueStep, _LengthViewStep, _DefaultStep]


def _may_mutate_memory(node: vy_ast.VyperNode) -> bool:
    """Conservatively identify expressions which can invalidate a borrowed pointer."""
    return bool(node.get_descendants(vy_ast.Call, include_self=True))


def _fold_constant(node: vy_ast.VyperNode, description: str) -> Any:
    folded = node.reduced()
    if not isinstance(folded, vy_ast.Constant):  # pragma: nocover
        raise CompilerPanic(f"unfoldable {description}", node)
    return folded.value


def _is_type_setting(settings: Any) -> bool:
    return TYPE_T.any().compare_type(settings.typ)


@dataclass(frozen=True)
class EvaluationPlan:
    """A linear plan which is the sole owner of runtime argument lowering."""

    steps: tuple[_EvaluationStep, ...]
    prepared_args: Mapping[int, PreparedArg]
    prepared_kwargs: Mapping[str, PreparedArg]
    list_lengths: Mapping[int, int]

    @classmethod
    def build(
        cls, signature: BuiltinSignature, lowerer: BuiltinLowerer, node: vy_ast.Call
    ) -> "EvaluationPlan":
        lowerer.validate(signature)
        prepared_args: dict[int, PreparedArg] = {}
        prepared_kwargs: dict[str, PreparedArg] = {}
        list_lengths: dict[int, int] = {}
        steps: list[_EvaluationStep] = []

        for index, arg_node in enumerate(node.args):
            arg_typ = signature.arg_types[index]
            if isinstance(arg_typ, TYPE_T):
                prepared_args[index] = TypeArgument(arg_typ.typedef)
                continue

            policy = lowerer.policy_for_arg(signature, index)
            if isinstance(policy, FoldedPolicy):
                prepared_args[index] = FoldedArgument(
                    _fold_constant(arg_node, f"argument {signature.arg_names[index]}")
                )
                continue

            if isinstance(policy, ValueListPolicy):
                reduced = arg_node.reduced()
                if not isinstance(reduced, vy_ast.List):  # pragma: nocover
                    raise CompilerPanic(
                        f"{signature.func_t._id}: {signature.arg_names[index]} must be a list",
                        arg_node,
                    )
                list_lengths[index] = len(reduced.elements)
                for element_index, element in enumerate(reduced.elements):
                    steps.append(_ValueStep(element, _ListDestination(index, element_index)))
                continue

            if isinstance(policy, (DataSourcePolicy, LengthPolicy)):
                view = classify_data_view(arg_node)
                if view is not None:
                    kind, address_node = view
                    if kind not in policy.allowed_views:
                        if isinstance(policy, DataSourcePolicy) and policy.unsupported_message:
                            raise CompilerPanic(policy.unsupported_message, arg_node)
                        # Route undeclared views through Expr so its established,
                        # source-specific diagnostic is retained.
                        destination: _Destination
                        if isinstance(policy, LengthPolicy):
                            destination = _LengthDestination(index)
                        else:
                            destination = _ArgDestination(index)
                        steps.append(_ValueStep(arg_node, destination))
                        continue

                    if address_node is None:
                        if isinstance(policy, LengthPolicy):
                            steps.append(_LengthViewStep(index, kind))
                        else:
                            prepared_args[index] = DataView(kind)
                    else:
                        steps.append(
                            _ValueStep(
                                address_node,
                                _ViewDestination(
                                    index, kind, as_length=isinstance(policy, LengthPolicy)
                                ),
                            )
                        )
                    continue

                destination = (
                    _LengthDestination(index)
                    if isinstance(policy, LengthPolicy)
                    else _ArgDestination(index)
                )
                steps.append(_ValueStep(arg_node, destination))
                continue

            if not isinstance(policy, ValuePolicy):  # pragma: nocover
                raise CompilerPanic(f"{signature.func_t._id}: unknown argument policy {policy}")
            steps.append(_ValueStep(arg_node, _ArgDestination(index)))

        kwarg_nodes: dict[str, vy_ast.VyperNode] = {}
        for kwarg in node.keywords:
            if kwarg.arg not in signature.kwarg_settings:  # pragma: nocover
                raise CompilerPanic(f"unexpected kwarg: {kwarg.arg}", kwarg)
            kwarg_nodes[kwarg.arg] = kwarg.value
            settings = signature.kwarg_settings[kwarg.arg]
            if _is_type_setting(settings):
                typ = kwarg.value._metadata.get("type")
                if not isinstance(typ, TYPE_T):  # pragma: nocover
                    raise CompilerPanic(f"{kwarg.arg}: expected a type argument", kwarg.value)
                prepared_kwargs[kwarg.arg] = TypeArgument(typ.typedef)
            elif settings.require_literal:
                prepared_kwargs[kwarg.arg] = FoldedArgument(
                    _fold_constant(kwarg.value, f"constant kwarg {kwarg.arg}")
                )
            else:
                steps.append(
                    _ValueStep(kwarg.value, _KwargDestination(kwarg.arg), reduce_node=True)
                )

        for name, settings in signature.kwarg_settings.items():
            if name in kwarg_nodes:
                continue
            if _is_type_setting(settings):
                if not isinstance(settings.default, VyperType):  # pragma: nocover
                    raise CompilerPanic(f"{name}: invalid type default {settings.default!r}")
                prepared_kwargs[name] = TypeArgument(settings.default)
            elif settings.require_literal:
                prepared_kwargs[name] = FoldedArgument(settings.default)
            else:
                steps.append(_DefaultStep(name, settings))

        # Snapshot a borrowed memory value only when a later source expression
        # may mutate an alias. Primitive words are loaded eagerly regardless.
        for index, step in enumerate(steps):
            if not isinstance(step, _ValueStep):
                continue
            later_nodes = [
                later.node for later in steps[index + 1 :] if isinstance(later, _ValueStep)
            ]
            if any(_may_mutate_memory(later) for later in later_nodes):
                steps[index] = replace(step, snapshot_memory=True)

        return cls(
            tuple(steps),
            MappingProxyType(prepared_args),
            MappingProxyType(prepared_kwargs),
            MappingProxyType(list_lengths),
        )


class PreparedBuiltinCall:
    """A builtin call whose runtime arguments are ready for emission-free access."""

    def __init__(
        self,
        func_t: "BuiltinFunctionT",
        node: vy_ast.Call,
        ctx: "VenomCodegenContext",
        lowerer: BuiltinLowerer,
    ):
        self.func_t = func_t
        self.node = node
        self.ctx = ctx
        self.signature = BuiltinSignature.from_call(func_t, node)
        self.provided_kwargs = frozenset(kwarg.arg for kwarg in node.keywords)

        plan = EvaluationPlan.build(self.signature, lowerer, node)
        self._args: dict[int, PreparedArg] = dict(plan.prepared_args)
        self._kwargs: dict[str, PreparedArg] = dict(plan.prepared_kwargs)
        list_values: dict[int, list[Optional[PreparedValue]]] = {
            index: [None] * length for index, length in plan.list_lengths.items()
        }

        for step in plan.steps:
            if isinstance(step, _DefaultStep):
                self._kwargs[step.name] = self._prepare_default(step.name, step.settings)
                continue

            if isinstance(step, _LengthViewStep):
                self._args[step.index] = self._prepare_view_length(step.kind)
                continue

            expr_node = step.node.reduced() if step.reduce_node else step.node
            from vyper.codegen_venom.expr import Expr

            vv = Expr(expr_node, ctx).lower()

            if isinstance(step.destination, _LengthDestination):
                self._args[step.destination.index] = self._prepare_length(vv)
                continue

            prepared = ctx.prepare_value(
                vv, snapshot_memory=step.snapshot_memory, annotation="builtin argument"
            )
            destination = step.destination
            if isinstance(destination, _ArgDestination):
                self._args[destination.index] = prepared
            elif isinstance(destination, _ListDestination):
                list_values[destination.index][destination.element_index] = prepared
            elif isinstance(destination, _ViewDestination):
                if destination.as_length:
                    address = prepared.word()
                    self._args[destination.index] = PreparedValue.from_word(
                        ctx.builder.extcodesize(address), UINT256_T
                    )
                else:
                    self._args[destination.index] = DataView(destination.kind, prepared)
            elif isinstance(destination, _KwargDestination):
                self._kwargs[destination.name] = prepared
            else:  # pragma: nocover
                raise CompilerPanic(f"unknown evaluation destination {destination}")

        for index, values in list_values.items():
            if any(value is None for value in values):  # pragma: nocover
                raise CompilerPanic(f"argument {index}: incomplete prepared list")
            self._args[index] = PreparedList(tuple(value for value in values if value is not None))

        if len(self._args) != len(node.args):  # pragma: nocover
            raise CompilerPanic(f"{func_t._id}: incomplete positional argument preparation")
        if set(self._kwargs) != set(self.signature.kwarg_settings):  # pragma: nocover
            raise CompilerPanic(f"{func_t._id}: incomplete keyword argument preparation")

    def _prepare_length(self, vv: VyperValue) -> PreparedValue:
        if vv.typ._is_prim_word:  # pragma: nocover
            raise CompilerPanic(f"len() expected a sequence, got {vv.typ}")
        length: IROperand
        if vv.location is None:
            if not isinstance(vv.operand, IRVariable):  # pragma: nocover
                raise CompilerPanic("len() expected a memory pointer")
            length = self.ctx.builder.mload(vv.operand)
        else:
            length = self.ctx.load_word(vv.operand, vv.location)
        return PreparedValue.from_word(length, UINT256_T)

    def _prepare_view_length(self, kind: DataViewKind) -> PreparedValue:
        if kind is DataViewKind.CALLDATA:
            length = self.ctx.builder.calldatasize()
        elif kind is DataViewKind.SELF_CODE:
            length = self.ctx.builder.codesize()
        else:  # pragma: nocover
            raise CompilerPanic(f"cannot prepare {kind.name.lower()} length without an address")
        return PreparedValue.from_word(length, UINT256_T)

    def _prepare_default(self, name: str, settings: Any) -> PreparedValue:
        typ = settings.typ
        if not isinstance(typ, VyperType) or not typ._is_prim_word:  # pragma: nocover
            raise CompilerPanic(f"{name}: unsupported runtime default type {typ}")

        default = settings.default
        operand: IROperand
        if default is ContextDefault.GAS:
            operand = self.ctx.builder.gas()
        elif type(default) is int:
            operand = IRLiteral(default)
        else:  # pragma: nocover
            raise CompilerPanic(f"{name}: unsupported runtime default {default!r}")
        return PreparedValue.from_word(operand, typ)

    @property
    def return_type(self) -> VyperType:
        return self.signature.return_type

    @property
    def arg_count(self) -> int:
        return len(self.node.args)

    def _arg_index(self, key: ArgKey) -> int:
        if isinstance(key, int):
            return key
        try:
            return self.signature.arg_names.index(key)
        except ValueError:  # pragma: nocover
            raise CompilerPanic(f"{self.func_t._id}: unknown argument {key}") from None

    def arg_type(self, key: ArgKey) -> Any:
        index = self._arg_index(key)
        return self.signature.arg_types[index]

    def source_arg(self, key: ArgKey) -> vy_ast.VyperNode:
        """Return the source node only for diagnostics which need an anchor."""
        index = self._arg_index(key)
        return self.node.args[index]

    def arg(self, key: ArgKey) -> PreparedValue:
        index = self._arg_index(key)
        value = self._args[index]
        if not isinstance(value, PreparedValue):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} arg {index} is {type(value).__name__}, requested value"
            )
        return value

    def arg_operand(self, key: ArgKey) -> IROperand:
        """Return an already-prepared operand without emitting IR."""
        return self.arg(key).operand

    def word(self, key: ArgKey) -> IROperand:
        return self.arg(key).word()

    def memory(self, key: ArgKey) -> IRVariable:
        operand = self.arg(key).ptr().operand
        if not isinstance(operand, IRVariable):  # pragma: nocover
            raise CompilerPanic(f"{self.func_t._id} arg {key} is not a memory variable")
        return operand

    def arg_operands(self) -> list[IROperand]:
        return [self.arg_operand(index) for index in range(self.arg_count)]

    def data_source(self, key: ArgKey) -> PreparedDataSource:
        index = self._arg_index(key)
        value = self._args[index]
        if not isinstance(value, (PreparedValue, DataView)):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} arg {index} is {type(value).__name__}, requested data source"
            )
        return value

    def value_list(self, key: ArgKey) -> tuple[PreparedValue, ...]:
        index = self._arg_index(key)
        value = self._args[index]
        if not isinstance(value, PreparedList):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} arg {index} is {type(value).__name__}, requested value list"
            )
        return value.values

    def type_arg(self, key: ArgKey) -> VyperType:
        index = self._arg_index(key)
        value = self._args[index]
        if not isinstance(value, TypeArgument):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} arg {index} is {type(value).__name__}, requested type"
            )
        return value.typ

    def folded_arg(self, key: ArgKey) -> Any:
        index = self._arg_index(key)
        value = self._args[index]
        if not isinstance(value, FoldedArgument):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} arg {index} is {type(value).__name__}, requested literal"
            )
        return value.value

    def kwarg_value(self, name: str) -> IROperand:
        value = self._kwargs[name]
        if not isinstance(value, PreparedValue):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} kwarg {name} is {type(value).__name__}, requested value"
            )
        return value.operand

    def literal(self, name: str) -> Any:
        value = self._kwargs[name]
        if not isinstance(value, FoldedArgument):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} kwarg {name} is {type(value).__name__}, requested literal"
            )
        return value.value

    def type_kwarg(self, name: str) -> VyperType:
        value = self._kwargs[name]
        if not isinstance(value, TypeArgument):  # pragma: nocover
            raise CompilerPanic(
                f"{self.func_t._id} kwarg {name} is {type(value).__name__}, requested type"
            )
        return value.typ

    def was_provided(self, name: str) -> bool:
        return name in self.provided_kwargs


__all__ = ["BuiltinLowerer", "PreparedBuiltinCall"]
