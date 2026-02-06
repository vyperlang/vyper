"""
String manipulation built-in functions.

- uint2str(x) - convert unsigned integer to decimal string
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.codegen_venom.buffer import Buffer
from vyper.codegen_venom.value import VyperValue
from vyper.venom.basicblock import IRLiteral

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_uint2str(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    uint2str(x) -> String[N]

    Convert unsigned integer to decimal string representation.

    Algorithm (matching legacy implementation):
    1. Special case: if x == 0, return "0"
    2. Loop: extract digits right-to-left using x % 10, store at buf + n_digits - i
    3. Each mstore writes a 32-byte word; the overlapping writes leave
       the least significant byte of each value at the correct position
    4. Store length at result_ptr = buf + n_digits - digit_count
    5. Return result_ptr

    Memory layout after construction (for "123"):
      result_ptr[0..31]  = length (3)
      result_ptr[32]     = '1' (0x31)
      result_ptr[33]     = '2' (0x32)
      result_ptr[34]     = '3' (0x33)
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    val_input = Expr(node.args[0], ctx).lower_value()
    out_t = node._metadata["type"]
    n_digits = out_t.maxlen

    # Allocate buffer
    out_val = ctx.new_temporary_value(out_t)
    buf = out_val.operand

    # Mutable variables
    val = b.new_variable()
    b.assign_to(val_input, val)

    i = b.new_variable()
    b.assign_to(IRLiteral(0), i)

    # Variable to hold the result pointer (will be set in both paths)
    result_ptr = b.new_variable()
    b.assign_to(buf, result_ptr)  # Initial dummy value

    # Control flow blocks
    check_zero = b.create_block("u2s_check")
    loop_cond = b.create_block("u2s_cond")
    loop_body = b.create_block("u2s_body")
    handle_zero = b.create_block("u2s_zero")
    finalize = b.create_block("u2s_final")
    exit_block = b.create_block("u2s_exit")

    b.jmp(check_zero.label)

    # === check_zero ===
    b.append_block(check_zero)
    b.set_block(check_zero)
    is_zero = b.eq(val, IRLiteral(0))
    b.jnz(is_zero, handle_zero.label, loop_cond.label)

    # === loop_cond ===
    b.append_block(loop_cond)
    b.set_block(loop_cond)
    done = b.eq(val, IRLiteral(0))
    b.jnz(done, finalize.label, loop_body.label)

    # === loop_body ===
    b.append_block(loop_body)
    b.set_block(loop_body)

    digit = b.mod(val, IRLiteral(10))
    char_val = b.add(IRLiteral(48), digit)

    # Store at buf + n_digits - i
    pos = b.sub(b.add(buf, IRLiteral(n_digits)), i)
    b.mstore(pos, char_val)

    new_val = b.div(val, IRLiteral(10))
    b.assign_to(new_val, val)
    new_i = b.add(i, IRLiteral(1))
    b.assign_to(new_i, i)

    b.jmp(loop_cond.label)

    # === handle_zero: input was 0 ===
    b.append_block(handle_zero)
    b.set_block(handle_zero)

    # Store "0": char at buf + n_digits, length 1 at buf + n_digits - 1
    zero_data_pos = b.add(buf, IRLiteral(n_digits))
    b.mstore(zero_data_pos, IRLiteral(ord("0")))

    zero_ptr = b.sub(b.add(buf, IRLiteral(n_digits)), IRLiteral(1))
    b.mstore(zero_ptr, IRLiteral(1))
    b.assign_to(zero_ptr, result_ptr)

    b.jmp(exit_block.label)

    # === finalize: nonzero path ===
    b.append_block(finalize)
    b.set_block(finalize)

    # result_ptr = buf + n_digits - i, store length i
    nonzero_ptr = b.sub(b.add(buf, IRLiteral(n_digits)), i)
    b.mstore(nonzero_ptr, i)
    b.assign_to(nonzero_ptr, result_ptr)

    b.jmp(exit_block.label)

    # === exit ===
    b.append_block(exit_block)
    b.set_block(exit_block)

    # result_ptr was set in both paths
    # Create a Buffer wrapper for the dynamic pointer
    result_buf = Buffer(_ptr=result_ptr, size=out_t.memory_bytes_required, annotation="uint2str")
    return VyperValue.from_ptr(result_buf.base_ptr(), out_t)


# Export handlers
HANDLERS = {"uint2str": lower_uint2str}
