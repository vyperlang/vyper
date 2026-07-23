"""
Hashing built-in functions.

- keccak256(data) - native EVM SHA3 opcode
- sha256(data) - SHA256 via precompile at address 0x2
"""

from __future__ import annotations

from vyper.codegen_venom.builtins._call import BuiltinLowerer, PreparedBuiltinCall
from vyper.semantics.types import BytesM_T
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable


def _prepare_hash_input(call: PreparedBuiltinCall) -> tuple[IROperand, IROperand]:
    """Normalize hash input to memory and return (data_ptr, length)."""
    ctx = call.ctx
    b = ctx.builder
    arg_t = call.arg_type("value")
    arg = call.arg("value")

    if isinstance(arg_t, _BytestringT):
        assert isinstance(arg.operand, IRVariable)
        return b.add(arg.operand, IRLiteral(32)), b.mload(arg.operand)

    # Fixed-size word values are hashed from a temporary 32-byte buffer.
    arg_val = arg.word()
    buf = ctx.allocate_buffer(32)
    b.mstore(buf._ptr, arg_val)

    if isinstance(arg_t, BytesM_T):
        return buf._ptr, IRLiteral(arg_t.m)
    return buf._ptr, IRLiteral(32)


def lower_keccak256(call: PreparedBuiltinCall) -> IROperand:
    """
    keccak256(data) -> bytes32

    Computes Keccak-256 hash using native SHA3 opcode.
    Handles both variable-length bytes/string and fixed bytes32.
    """
    b = call.ctx.builder
    data_ptr, length = _prepare_hash_input(call)
    return b.sha3(data_ptr, length)


def lower_sha256(call: PreparedBuiltinCall) -> IROperand:
    """
    sha256(data) -> bytes32

    Computes SHA-256 hash via precompile at address 0x2.
    """
    ctx = call.ctx
    b = ctx.builder
    data_ptr, length = _prepare_hash_input(call)
    assert isinstance(data_ptr, IRVariable)

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
HANDLERS = {"keccak256": BuiltinLowerer(lower_keccak256), "sha256": BuiltinLowerer(lower_sha256)}
