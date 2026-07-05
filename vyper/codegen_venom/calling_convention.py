"""
Internal function calling convention for Venom codegen.

Determines how arguments and return values are passed between
internal functions: via the EVM stack or via memory pointers.

This module is the single source of truth for these decisions.
"""

from __future__ import annotations

from vyper.codegen.core import is_tuple_like
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import (
    VyperType,
    is_supported_unbounded_tuple_type,
    is_unbounded_sequence_type,
    type_contains_unbounded_sequence,
)
from vyper.semantics.types.subscriptable import TupleT

# Maximum number of word-type arguments passed via the stack.
MAX_STACK_ARGS = 6

# Maximum number of word-type return values passed via the stack (for tuples).
MAX_STACK_RETURNS = 2


def is_dynamic_tuple_return_type(typ: VyperType | None) -> bool:
    return isinstance(typ, TupleT) and type_contains_unbounded_sequence(typ)


def is_dynamic_tuple_dynamic_member_type(typ: VyperType) -> bool:
    return is_unbounded_sequence_type(typ) or not typ._is_prim_word


def validate_dynamic_tuple_return_type(typ: VyperType | None) -> None:
    if not is_dynamic_tuple_return_type(typ):
        return

    assert isinstance(typ, TupleT)
    if not is_supported_unbounded_tuple_type(typ):
        raise CompilerPanic(
            "semantic analysis should reject nested INF tuple returns"
        )  # pragma: nocover


def is_word_type(typ: VyperType) -> bool:
    """Check if type is a primitive word type that fits in one stack slot.

    Must be both 32 bytes AND a primitive word type. Compound types like
    uint256[1] are 32 bytes but not primitive words - they must be passed
    via memory pointer, not by value on the stack.
    """
    if is_unbounded_sequence_type(typ):
        return False

    return typ.memory_bytes_required == 32 and typ._is_prim_word


def returns_dynamic_count(func_t) -> int:
    """How many memory-copy return pairs are returned via `dret`."""
    ret_t = func_t.return_type
    if is_unbounded_sequence_type(ret_t):
        return 1
    if is_dynamic_tuple_return_type(ret_t):
        validate_dynamic_tuple_return_type(ret_t)
        return sum(
            1 for member_t in ret_t.member_types if is_dynamic_tuple_dynamic_member_type(member_t)
        )
    return 0


def returns_stack_count(func_t) -> int:
    """How many ordinary values are returned via stack.

    Plain bounded tuple returns still use the historical 0/1/2 stack-return
    cutoff. Dynamic tuple returns may pair more ordinary stack outputs with
    one or more `dret` dynamic outputs.
    """
    ret_t = func_t.return_type
    if ret_t is None:
        return 0

    if is_dynamic_tuple_return_type(ret_t):
        validate_dynamic_tuple_return_type(ret_t)
        return sum(
            1
            for member_t in ret_t.member_types
            if not is_dynamic_tuple_dynamic_member_type(member_t)
        )

    if is_tuple_like(ret_t):
        members = ret_t.tuple_items()
        if 1 <= len(members) <= MAX_STACK_RETURNS:
            if all(is_word_type(t) for (_k, t) in members):
                return len(members)
        return 0

    return 1 if is_word_type(ret_t) else 0


def pass_via_stack(func_t) -> dict[str, bool]:
    """Determine which args pass via stack vs memory.

    Returns dict mapping arg name -> True if stack, False if memory.
    Primitive word types pass via stack up to MAX_STACK_ARGS.
    """
    ret = {}
    stack_items = 0

    # Reserve stack slots for return values
    stack_items += returns_stack_count(func_t) + returns_dynamic_count(func_t)

    for arg in func_t.arguments:
        if not is_word_type(arg.typ) or stack_items >= MAX_STACK_ARGS:
            ret[arg.name] = False
        else:
            ret[arg.name] = True
            stack_items += 1

    return ret
