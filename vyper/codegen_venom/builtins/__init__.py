"""
Built-in function lowering for Venom IR.

Each submodule exports a HANDLERS dict mapping builtin_id -> handler function.
Handler signature: (node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand
"""

from vyper.exceptions import CompilerPanic

from .bytes import HANDLERS as BYTES_HANDLERS
from .hashing import HANDLERS as HASHING_HANDLERS
from .math import HANDLERS as MATH_HANDLERS
from .simple import HANDLERS as SIMPLE_HANDLERS

# Combine all handlers
BUILTIN_HANDLERS: dict = {
    **SIMPLE_HANDLERS,
    **MATH_HANDLERS,
    **HASHING_HANDLERS,
    **BYTES_HANDLERS,
    # More will be added as implemented:
    # **CONVERT_HANDLERS,
    # **ABI_HANDLERS,
    # **RAW_HANDLERS,
    # **CREATE_HANDLERS,
    # **MISC_HANDLERS,
}


def lower_builtin(builtin_id: str, node, ctx) -> "IROperand":  # noqa: F821
    """
    Lower a built-in function call to Venom IR.

    Args:
        builtin_id: The builtin's _id (e.g., "len", "keccak256")
        node: The vy_ast.Call node
        ctx: VenomCodegenContext

    Returns:
        IROperand representing the result
    """
    handler = BUILTIN_HANDLERS.get(builtin_id)
    if handler is None:
        raise CompilerPanic(f"Built-in '{builtin_id}' not yet implemented in venom codegen")
    return handler(node, ctx)
