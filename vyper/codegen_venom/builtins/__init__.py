"""
Built-in function lowering for Venom IR.

Each submodule exports a HANDLERS dict mapping builtin_id -> handler function.
Handler signature: (call: BuiltinCall) -> IROperand | VyperValue

Builtins that return memory-located data (abi_decode, concat, slice, etc.)
should return VyperValue.from_ptr() to preserve location info. Builtins that return
stack values can return IROperand directly.
"""

from __future__ import annotations

from typing import Union

from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IROperand

from vyper.codegen_venom.value import VyperValue

from ._kwargs import BuiltinCall
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

# Combine all handlers
BUILTIN_HANDLERS: dict = {
    **SIMPLE_HANDLERS,
    **MATH_HANDLERS,
    **HASHING_HANDLERS,
    **BYTES_HANDLERS,
    **CONVERT_HANDLERS,
    **ABI_HANDLERS,
    **SYSTEM_HANDLERS,
    **CREATE_HANDLERS,
    **MISC_HANDLERS,
    **STRINGS_HANDLERS,
}

RUNTIME_ARG_INDICES: dict[str, frozenset[int]] = {
    "abi_decode": frozenset((0,)),
    "_abi_decode": frozenset((0,)),
    "convert": frozenset((0,)),
    "empty": frozenset(),
    "len": frozenset(),
    "min_value": frozenset(),
    "max_value": frozenset(),
    "epsilon": frozenset(),
    "raw_log": frozenset(),
    "slice": frozenset(),
}

RUNTIME_KWARGS: dict[str, frozenset[str]] = {
    "raw_call": frozenset(("gas", "value")),
    "send": frozenset(("gas",)),
    "raw_create": frozenset(("value", "salt")),
    "create_minimal_proxy_to": frozenset(("value", "salt")),
    "create_forwarder_to": frozenset(("value", "salt")),
    "create_copy_of": frozenset(("value", "salt")),
    "create_from_blueprint": frozenset(("value", "salt", "code_offset")),
}

MATERIALIZE_COMPLEX_ARGS = frozenset(("raw_create", "create_from_blueprint"))


def lower_builtin(builtin_id: str, node, ctx) -> Union[IROperand, VyperValue]:
    """
    Lower a built-in function call to Venom IR.

    Args:
        builtin_id: The builtin's _id (e.g., "len", "keccak256")
        node: The vy_ast.Call node
        ctx: VenomCodegenContext

    Returns:
        IROperand for stack values, or VyperValue for memory-located results
    """
    handler = BUILTIN_HANDLERS.get(builtin_id)
    if handler is None:  # pragma: nocover
        raise CompilerPanic(f"Built-in '{builtin_id}' not yet implemented in venom codegen")
    return handler(
        BuiltinCall(
            node,
            ctx,
            runtime_arg_indices=RUNTIME_ARG_INDICES.get(builtin_id),
            runtime_kwarg_names=RUNTIME_KWARGS.get(builtin_id, frozenset()),
            materialize_complex_args=builtin_id in MATERIALIZE_COMPLEX_ARGS,
        )
    )
