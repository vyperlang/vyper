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


def lower_keccak256(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    keccak256(data) -> bytes32

    Computes Keccak-256 hash using native SHA3 opcode.
    Handles both variable-length bytes/string and fixed bytes32.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    arg_node = node.args[0]
    arg_t = arg_node._metadata["type"]

    if isinstance(arg_t, _BytestringT):
        # Variable-length bytes/string: ptr points to length word
        # Data starts at ptr + 32
        # sha3(length, data_ptr) - builder emits in EVM order
        arg_vv = Expr(arg_node, ctx).lower()
        data_ptr = ctx.bytes_data_ptr(arg_vv)
        length = ctx.bytestring_length(arg_vv)
        return b.sha3(length, data_ptr)
    elif isinstance(arg_t, BytesM_T):
        # Fixed bytesM: need to put value in memory first
        # The value is already left-aligned in 32 bytes
        arg_val = Expr(arg_node, ctx).lower_value()
        buf = ctx.allocate_buffer(32)
        b.mstore(arg_val, buf)
        return b.sha3(IRLiteral(arg_t.m), buf)
    else:
        # bytes32 or other 32-byte type
        arg_val = Expr(arg_node, ctx).lower_value()
        buf = ctx.allocate_buffer(32)
        b.mstore(arg_val, buf)
        return b.sha3(IRLiteral(32), buf)


def lower_sha256(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    sha256(data) -> bytes32

    Computes SHA-256 hash via precompile at address 0x2.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    arg_node = node.args[0]
    arg_t = arg_node._metadata["type"]

    data_ptr: IROperand
    length: IROperand
    if isinstance(arg_t, _BytestringT):
        # Variable-length bytes/string
        arg_vv = Expr(arg_node, ctx).lower()
        data_ptr = ctx.bytes_data_ptr(arg_vv)
        length = ctx.bytestring_length(arg_vv)
    elif isinstance(arg_t, BytesM_T):
        # Fixed bytesM
        arg_val = Expr(arg_node, ctx).lower_value()
        buf = ctx.allocate_buffer(32)
        b.mstore(arg_val, buf)
        data_ptr = buf
        length = IRLiteral(arg_t.m)
    else:
        # bytes32 or other 32-byte type
        arg_val = Expr(arg_node, ctx).lower_value()
        buf = ctx.allocate_buffer(32)
        b.mstore(arg_val, buf)
        data_ptr = buf
        length = IRLiteral(32)

    # Allocate output buffer (32 bytes for hash result)
    out_buf = ctx.allocate_buffer(32)

    # Call SHA256 precompile: staticcall(gas, 0x2, in_ptr, in_len, out_ptr, 32)
    success = b.staticcall(
        b.gas(), IRLiteral(2), data_ptr, length, out_buf, IRLiteral(32)  # SHA256 precompile address
    )

    # Assert success (precompile should always succeed with valid input)
    b.assert_(success)

    return b.mload(out_buf)


# Export handlers
HANDLERS = {"keccak256": lower_keccak256, "sha256": lower_sha256}
