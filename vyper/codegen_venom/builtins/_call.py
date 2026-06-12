"""
Uniform entry point for builtin call lowering.

`lower_builtin()` wraps every builtin callsite in a `BuiltinCall`, which
validates keyword arguments against the builtin's declared interface and
lowers all runtime expressions -- positional args first, then keyword
args -- exactly once, in source order, *before* the `lower_<builtin>`
handler runs. Handlers consume pre-lowered values; they never lower
argument expressions themselves.

A builtin with keyword arguments (or positional args it must lower
itself) declares its interface with the `@callsite` decorator:

    @callsite(
        constant_kwargs={"revert_on_failure": True},
        runtime_kwargs={"value": 0, "salt": None},
    )
    def lower_raw_create(call: BuiltinCall) -> IROperand: ...

- `constant_kwargs` must fold to compile-time constants.
  `call.kwarg_constants` maps each declared name to its python value,
  with defaults filled in.
- `runtime_kwargs` are lowered in the user's keyword order.
  `call.kwarg_values` maps each declared name to an `IROperand`, with
  defaults filled in. A default may be an int (becomes an `IRLiteral`),
  a callable taking the codegen context (invoked when the kwarg is
  missing, e.g. to emit `gas`), or None (no default -- the value stays
  None when the kwarg is not provided, e.g. `salt`, where presence
  selects CREATE2 over CREATE).
- `type_kwargs` are type expressions consumed during semantic analysis
  (e.g. `extract32(..., output_type=...)`); they are accepted by
  validation but have no runtime value.
- `handler_args` lists positional args the handler lowers itself
  because they have no uniform value form (e.g. `raw_log`'s topics list
  literal). Everything else is pre-lowered.

Two kinds of positional args are skipped generically:

- type expressions (`empty(T)`, `convert(x, T)`) have no runtime value;
- data views (`msg.data`, `self.code`, `<address>.code`) denote raw data
  locations accessed via calldatacopy/codecopy/extcodecopy. For
  `<address>.code`, the address subexpression is the view's only runtime
  component and is lowered in the arg's place, preserving source order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from vyper import ast as vy_ast
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import TYPE_T, AddressT
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext

RuntimeDefault = Union[int, None, Callable[["VenomCodegenContext"], IROperand]]


@dataclass(frozen=True)
class CallsiteSpec:
    constant_kwargs: dict[str, Any]
    runtime_kwargs: dict[str, RuntimeDefault]
    type_kwargs: tuple[str, ...]
    handler_args: tuple[int, ...]

    def __post_init__(self):
        kinds = (set(self.constant_kwargs), set(self.runtime_kwargs), set(self.type_kwargs))
        assert len(set().union(*kinds)) == sum(
            len(kind) for kind in kinds
        ), "kwarg declared with more than one kind"

    @property
    def allowed_kwargs(self) -> set[str]:
        return set(self.constant_kwargs) | set(self.runtime_kwargs) | set(self.type_kwargs)


DEFAULT_SPEC = CallsiteSpec({}, {}, (), ())


def callsite(
    constant_kwargs: Optional[dict[str, Any]] = None,
    runtime_kwargs: Optional[dict[str, RuntimeDefault]] = None,
    type_kwargs: tuple[str, ...] = (),
    handler_args: tuple[int, ...] = (),
):
    """Declare a builtin handler's callsite interface (see module docstring)."""

    def decorator(handler):
        handler._callsite_spec = CallsiteSpec(
            constant_kwargs or {}, runtime_kwargs or {}, type_kwargs, handler_args
        )
        return handler

    return decorator


def is_msg_data(node: vy_ast.VyperNode) -> bool:
    """Check for `msg.data`."""
    return (
        isinstance(node, vy_ast.Attribute)
        and node.attr == "data"
        and isinstance(node.value, vy_ast.Name)
        and node.value.id == "msg"
    )


def is_data_view(node: vy_ast.VyperNode) -> bool:
    """Check for `msg.data`, `self.code` or `<address>.code`."""
    if is_msg_data(node):
        return True
    if not isinstance(node, vy_ast.Attribute):
        return False
    if isinstance(node.value, vy_ast.Name) and node.value.id == "self" and node.attr == "code":
        return True
    return node.attr == "code" and isinstance(node.value._metadata.get("type"), AddressT)


def _data_view_address(node: vy_ast.Attribute) -> Optional[vy_ast.VyperNode]:
    """The address subexpression of an `<address>.code` view, if any."""
    if isinstance(node.value, vy_ast.Name) and node.value.id in ("msg", "self"):
        return None
    return node.value


def _may_have_side_effects(node: vy_ast.VyperNode) -> bool:
    """Whether evaluating the expression can mutate observable state.

    Conservative: any call (internal call, builtin, mutating method call
    like `arr.append(...)`) counts as a side effect.
    """
    return len(node.get_descendants(vy_ast.Call, include_self=True)) > 0


class BuiltinCall:
    """A builtin callsite, prepared for lowering.

    Construction validates keyword arguments and lowers every runtime
    expression exactly once, in source order: positional args first,
    then keyword args. An argument value is frozen (loaded onto the
    stack or copied into a fresh temporary) when a later expression has
    side effects, so it cannot be mutated between evaluation and use.
    """

    node: vy_ast.Call
    ctx: "VenomCodegenContext"
    # explicitly provided kwarg names (e.g. presence of `value=` is an
    # error for static raw_calls even though it has a default)
    provided_kwargs: frozenset[str]
    # declared constant kwargs, folded to python values, defaults filled
    kwarg_constants: dict[str, Any]
    # declared runtime kwargs, lowered in keyword order, defaults filled
    kwarg_values: dict[str, Optional[IROperand]]
    # pre-lowered positional args; None for compile-time-only args
    arg_values: list[Optional[VyperValue]]

    def __init__(self, node: vy_ast.Call, ctx, spec: CallsiteSpec = DEFAULT_SPEC):
        self.node = node
        self.ctx = ctx

        kwarg_nodes = self._validate_kwargs(spec)
        self.provided_kwargs = frozenset(kwarg_nodes)

        self.kwarg_constants = self._fold_constant_kwargs(kwarg_nodes, spec)
        self.arg_values = self._lower_args(kwarg_nodes, spec)
        self.kwarg_values = self._lower_runtime_kwargs(kwarg_nodes, spec)

    def kwarg_value(self, name: str) -> IROperand:
        """A runtime kwarg whose default guarantees it a value. Kwargs
        without a default (e.g. salt) are accessed via `kwarg_values`."""
        value = self.kwarg_values[name]
        assert value is not None
        return value

    def arg(self, index: int) -> VyperValue:
        vv = self.arg_values[index]
        assert vv is not None, "requested arg was not pre-lowered"
        return vv

    def arg_operand(self, index: int) -> IROperand:
        """Unwrap a pre-lowered arg: a stack value for primitive words,
        a memory pointer for composite types."""
        return self.ctx.unwrap(self.arg(index))

    def arg_operands(self) -> list[IROperand]:
        return [self.arg_operand(i) for i in range(len(self.node.args))]

    def _validate_kwargs(self, spec: CallsiteSpec) -> dict[str, vy_ast.VyperNode]:
        allowed = spec.allowed_kwargs
        ret = {}
        for kw in self.node.keywords:
            if kw.arg not in allowed:  # pragma: nocover
                raise CompilerPanic(f"unexpected kwarg: {kw.arg}", kw)
            ret[kw.arg] = kw.value
        return ret

    def _fold_constant_kwargs(
        self, kwarg_nodes: dict[str, vy_ast.VyperNode], spec: CallsiteSpec
    ) -> dict[str, Any]:
        ret = {}
        for name, default in spec.constant_kwargs.items():
            if name in kwarg_nodes:
                folded = kwarg_nodes[name].reduced()
                if not isinstance(folded, vy_ast.Constant):  # pragma: nocover
                    raise CompilerPanic(f"unfoldable constant kwarg: {name}", folded)
                ret[name] = folded.value
            else:
                ret[name] = default
        return ret

    def _lower_args(
        self, kwarg_nodes: dict[str, vy_ast.VyperNode], spec: CallsiteSpec
    ) -> list[Optional[VyperValue]]:
        from vyper.codegen_venom.expr import Expr

        args = self.node.args
        runtime_kwarg_nodes = [
            node for name, node in kwarg_nodes.items() if name in spec.runtime_kwargs
        ]

        ret: list[Optional[VyperValue]] = []
        for i, arg in enumerate(args):
            vv: Optional[VyperValue] = None
            if i in spec.handler_args or isinstance(arg._metadata.get("type"), TYPE_T):
                pass
            elif is_data_view(arg):
                assert isinstance(arg, vy_ast.Attribute)
                address = _data_view_address(arg)
                if address is not None:
                    operand = Expr(address, self.ctx).lower_value()
                    vv = VyperValue.from_stack_op(operand, address._metadata["type"])
            else:
                vv = Expr(arg, self.ctx).lower()

            later_nodes = list(args[i + 1 :]) + runtime_kwarg_nodes
            if vv is not None and any(_may_have_side_effects(n) for n in later_nodes):
                vv = self._freeze(vv)
            ret.append(vv)
        return ret

    def _lower_runtime_kwargs(
        self, kwarg_nodes: dict[str, vy_ast.VyperNode], spec: CallsiteSpec
    ) -> dict[str, Optional[IROperand]]:
        from vyper.codegen_venom.expr import Expr

        ret: dict[str, Optional[IROperand]] = {}
        # explicit kwargs first, in the user's keyword order
        for name, node in kwarg_nodes.items():
            if name in spec.runtime_kwargs:
                ret[name] = Expr(node.reduced(), self.ctx).lower_value()

        for name, default in spec.runtime_kwargs.items():
            if name in ret:
                continue
            if default is None:
                ret[name] = None
            elif callable(default):
                ret[name] = default(self.ctx)
            else:
                ret[name] = IRLiteral(default)
        return ret

    def _freeze(self, vv: VyperValue) -> VyperValue:
        """Snapshot a value so later side effects cannot change it."""
        if vv.typ._is_prim_word:
            return VyperValue.from_stack_op(self.ctx.unwrap(vv), vv.typ)
        return self.ctx.materialize_value(vv, annotation="builtin arg")
