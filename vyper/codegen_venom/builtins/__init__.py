"""
Built-in function lowering for Venom IR.

Each submodule exports a HANDLERS dict mapping builtin_id -> BuiltinLowerer.

`lower_builtin` binds the semantic signature and executes a source-ordered
argument plan before the handler runs; see `_call.py` for the prepared boundary.

Builtins that return memory-located data (abi_decode, concat, slice, etc.)
should return VyperValue.from_ptr() to preserve location info. Builtins that return
stack values can return IROperand directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Union

from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IROperand

from ._call import BuiltinLowerer, PreparedBuiltinCall
from .abi import HANDLERS as ABI_HANDLERS
from .bytes import HANDLERS as BYTES_HANDLERS
from .convert import HANDLERS as CONVERT_HANDLERS
from .create import HANDLERS as CREATE_HANDLERS
from .hashing import HANDLERS as HASHING_HANDLERS
from .math import HANDLERS as MATH_HANDLERS
from .misc import HANDLERS as MISC_HANDLERS
from .simple import HANDLERS as SIMPLE_HANDLERS
from .strings import HANDLERS as STRINGS_HANDLERS
from .system import HANDLERS as SYSTEM_HANDLERS

__all__ = ["BUILTIN_HANDLERS", "lower_builtin"]

if TYPE_CHECKING:
    from vyper.builtins._signatures import BuiltinFunctionT


def _merge_handlers(*handler_maps: Mapping[str, BuiltinLowerer]) -> dict[str, BuiltinLowerer]:
    ret: dict[str, BuiltinLowerer] = {}
    for handlers in handler_maps:
        duplicates = set(ret).intersection(handlers)
        if duplicates:  # pragma: nocover
            names = ", ".join(sorted(duplicates))
            raise CompilerPanic(f"duplicate Venom builtin handlers: {names}")
        ret.update(handlers)
    return ret


def _validate_handler_result(
    call: PreparedBuiltinCall, result: Union[IROperand, VyperValue]
) -> Union[IROperand, VyperValue]:
    if isinstance(result, VyperValue) and not result.typ.compare_type(call.return_type):
        raise CompilerPanic(
            f"Builtin '{call.func_t._id}' returned {result.typ}, expected {call.return_type}"
        )
    return result


BUILTIN_HANDLERS = _merge_handlers(
    SIMPLE_HANDLERS,
    MATH_HANDLERS,
    HASHING_HANDLERS,
    BYTES_HANDLERS,
    CONVERT_HANDLERS,
    ABI_HANDLERS,
    SYSTEM_HANDLERS,
    CREATE_HANDLERS,
    MISC_HANDLERS,
    STRINGS_HANDLERS,
)


def lower_builtin(func_t: "BuiltinFunctionT", node, ctx) -> Union[IROperand, VyperValue]:
    """
    Lower a built-in function call to Venom IR.

    Args:
        func_t: The concrete semantic builtin type for this callsite.
        node: The vy_ast.Call node
        ctx: VenomCodegenContext

    Returns:
        IROperand for stack values, or VyperValue for memory-located results
    """
    lowerer = BUILTIN_HANDLERS.get(func_t._id)
    if lowerer is None:  # pragma: nocover
        raise CompilerPanic(f"Built-in '{func_t._id}' not yet implemented in venom codegen")
    call = PreparedBuiltinCall(func_t, node, ctx, lowerer)
    return _validate_handler_result(call, lowerer.handler(call))
