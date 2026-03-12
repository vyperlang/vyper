"""
Internal function calling convention for Venom codegen.

Determines how arguments and return values are passed between
internal functions: via the EVM stack or via memory pointers.

This module is the single source of truth for these decisions.
"""
from __future__ import annotations

from vyper.codegen.core import is_tuple_like
from vyper.semantics.types import VyperType

# Maximum number of word-type arguments passed via the stack.
MAX_STACK_ARGS = 6

# Maximum number of word-type return values passed via the stack (for tuples).
MAX_STACK_RETURNS = 2


def is_word_type(typ: VyperType) -> bool:
    """Check if type is a primitive word type that fits in one stack slot.

    Must be both 32 bytes AND a primitive word type. Compound types like
    uint256[1] are 32 bytes but not primitive words - they must be passed
    via memory pointer, not by value on the stack.
    """
    return typ.memory_bytes_required == 32 and typ._is_prim_word


def returns_stack_count(func_t) -> int:
    """How many values returned via stack (0, 1, or 2 for tuples)."""
    ret_t = func_t.return_type
    if ret_t is None:
        return 0

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

    # Return takes one stack slot if it's a word type
    if func_t.return_type is not None and is_word_type(func_t.return_type):
        stack_items += 1

    for arg in func_t.arguments:
        if not is_word_type(arg.typ) or stack_items > MAX_STACK_ARGS:
            ret[arg.name] = False
        else:
            ret[arg.name] = True
            stack_items += 1

    return ret
