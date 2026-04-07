"""
Hashing built-in functions.

- keccak256(data) - native EVM SHA3 opcode
- sha256(data) - SHA256 via precompile at address 0x2
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.semantics.types import BytesM_T
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _prepare_hash_input(node: vy_ast.Call, ctx: VenomCodegenContext) -> tuple[IROperand, IROperand]:
    """Normalize hash input to memory and return (data_ptr, length)."""
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder
    arg_node = node.args[0]
    arg_t = arg_node._metadata["type"]

    if isinstance(arg_t, _BytestringT):
        arg_vv = Expr(arg_node, ctx).lower()
        arg_mem = ctx.ensure_bytestring_in_memory(arg_vv, arg_t)
        return ctx.bytes_data_ptr(arg_mem), ctx.bytestring_length(arg_mem)

    # Fixed-size word values are hashed from a temporary 32-byte buffer.
    arg_val = Expr(arg_node, ctx).lower_value()
    buf = ctx.allocate_buffer(32)
    b.mstore(buf._ptr, arg_val)

    if isinstance(arg_t, BytesM_T):
        return buf._ptr, IRLiteral(arg_t.m)
    return buf._ptr, IRLiteral(32)


def lower_keccak256(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    keccak256(data) -> bytes32

    Computes Keccak-256 hash using native SHA3 opcode.
    Handles both variable-length bytes/string and fixed bytes32.
    """
    b = ctx.builder
    data_ptr, length = _prepare_hash_input(node, ctx)
    return b.sha3(data_ptr, length)


def lower_sha256(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    sha256(data) -> bytes32

    Computes SHA-256 hash via precompile at address 0x2.
    """
    b = ctx.builder
    data_ptr, length = _prepare_hash_input(node, ctx)

    # Allocate output buffer (32 bytes for hash result)
    out_buf = ctx.allocate_buffer(32)

    # Call SHA256 precompile: staticcall(gas, 0x2, in_ptr, in_len, out_ptr, 32)
    success = b.staticcall(
        b.gas(),
        IRLiteral(2),
        data_ptr,
        length,
        out_buf._ptr,
        IRLiteral(32),  # SHA256 precompile address
    )

    # Assert success (precompile should always succeed with valid input)
    b.assert_(success)

    return b.mload(out_buf._ptr)


# Export handlers
HANDLERS = {"keccak256": lower_keccak256, "sha256": lower_sha256}
