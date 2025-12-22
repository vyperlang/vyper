"""
System-level built-in functions for raw operations.

- raw_call(to, data, ...) - low-level external call
- send(to, value, gas=0) - send ether with optional gas stipend
- raw_log(topics, data) - low-level event emission
- raw_revert(data) - revert with custom data
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.semantics.types import BytesM_T, BytesT, TupleT
from vyper.semantics.types.shortcuts import BYTES32_T, UINT256_T
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _get_kwarg_value(node: vy_ast.Call, kwarg_name: str, default=None):
    """Extract a keyword argument value from a Call node."""
    for kw in node.keywords:
        if kw.arg == kwarg_name:
            return kw.value
    return default


def _get_literal_kwarg(node: vy_ast.Call, kwarg_name: str, default):
    """Extract a literal value from a keyword argument."""
    kw_node = _get_kwarg_value(node, kwarg_name)
    if kw_node is None:
        return default
    # Try to get folded value
    if hasattr(kw_node, "get_folded_value"):
        folded = kw_node.get_folded_value()
        if isinstance(folded, vy_ast.Int):
            return folded.value
        if isinstance(folded, vy_ast.NameConstant):
            return folded.value
    # Try direct value
    if isinstance(kw_node, vy_ast.Int):
        return kw_node.value
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value
    return default


def lower_raw_call(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    raw_call(to, data, max_outsize=0, gas=gas, value=0,
             is_delegate_call=False, is_static_call=False,
             revert_on_failure=True)

    Low-level external call with full control over parameters.

    Returns:
        - None if max_outsize=0 and revert_on_failure=True
        - bool if max_outsize=0 and revert_on_failure=False
        - Bytes[N] if max_outsize>0 and revert_on_failure=True
        - (bool, Bytes[N]) if max_outsize>0 and revert_on_failure=False
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    # Parse positional args
    to = Expr(node.args[0], ctx).lower()
    data = Expr(node.args[1], ctx).lower()

    # Parse kwargs
    max_outsize = _get_literal_kwarg(node, "max_outsize", 0)
    is_delegate = _get_literal_kwarg(node, "is_delegate_call", False)
    is_static = _get_literal_kwarg(node, "is_static_call", False)
    revert_on_failure = _get_literal_kwarg(node, "revert_on_failure", True)

    # Handle gas kwarg - defaults to remaining gas
    gas_node = _get_kwarg_value(node, "gas")
    if gas_node is None:
        gas = b.gas()
    else:
        gas = Expr(gas_node, ctx).lower()

    # Handle value kwarg - only for regular call
    value_node = _get_kwarg_value(node, "value")
    if value_node is None:
        value = IRLiteral(0)
    else:
        value = Expr(value_node, ctx).lower()

    # Get input data pointer and length
    # Bytes layout: [32-byte length][data...]
    data_len = b.mload(data)
    data_ptr = b.add(data, IRLiteral(32))

    # Allocate output buffer if needed
    if max_outsize > 0:
        out_buf = ctx.new_internal_variable(BytesT(max_outsize))
        out_ptr = b.add(out_buf, IRLiteral(32))
    else:
        out_buf = None
        out_ptr = IRLiteral(0)

    # Build the call instruction
    if is_delegate:
        # delegatecall(gas, to, argsptr, argsz, retptr, retsz)
        success = b.delegatecall(gas, to, data_ptr, data_len, out_ptr, IRLiteral(max_outsize))
    elif is_static:
        # staticcall(gas, to, argsptr, argsz, retptr, retsz)
        success = b.staticcall(gas, to, data_ptr, data_len, out_ptr, IRLiteral(max_outsize))
    else:
        # call(gas, to, value, argsptr, argsz, retptr, retsz)
        success = b.call(gas, to, value, data_ptr, data_len, out_ptr, IRLiteral(max_outsize))

    # Handle return based on revert_on_failure and max_outsize
    if revert_on_failure:
        b.assert_(success)
        if max_outsize > 0:
            # Store actual return size (capped at max_outsize)
            ret_size = b.returndatasize()
            # min(ret_size, max_outsize)
            capped = b.select(
                b.lt(ret_size, IRLiteral(max_outsize)),
                ret_size,
                IRLiteral(max_outsize),
            )
            b.mstore(capped, out_buf)
            return out_buf
        # No return value (returns None in Vyper)
        return IRLiteral(0)
    else:
        if max_outsize > 0:
            # Store actual return size (capped at max_outsize)
            ret_size = b.returndatasize()
            capped = b.select(
                b.lt(ret_size, IRLiteral(max_outsize)),
                ret_size,
                IRLiteral(max_outsize),
            )
            b.mstore(capped, out_buf)

            # Return (success, data) tuple
            # Allocate tuple: [bool (32 bytes)][ptr (32 bytes)]
            tuple_t = TupleT([UINT256_T, BytesT(max_outsize)])
            tuple_buf = ctx.new_internal_variable(tuple_t)
            b.mstore(success, tuple_buf)
            b.mstore(out_buf, b.add(tuple_buf, IRLiteral(32)))
            return tuple_buf

        # Just return success flag
        return success


def lower_send(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    send(to, value, gas=0)

    Send ether to address. Reverts on failure.
    The gas kwarg defaults to 0 (empty gas stipend) in Vyper.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    to = Expr(node.args[0], ctx).lower()
    value = Expr(node.args[1], ctx).lower()

    # Parse gas kwarg (default 0)
    gas_node = _get_kwarg_value(node, "gas")
    if gas_node is None:
        gas = IRLiteral(0)
    else:
        gas = Expr(gas_node, ctx).lower()

    # call(gas, to, value, 0, 0, 0, 0)
    success = b.call(
        gas,
        to,
        value,
        IRLiteral(0),  # No input data
        IRLiteral(0),
        IRLiteral(0),  # No output
        IRLiteral(0),
    )

    # send() asserts success
    b.assert_(success)

    return IRLiteral(0)  # Statement builtin, no return


def lower_raw_log(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    raw_log(topics, data)

    Emit a raw log with 0-4 topics.
    - topics: list of bytes32 values (compile-time fixed length)
    - data: bytes32 or Bytes[N]
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    topics_node = node.args[0]
    data_node = node.args[1]

    # Get the reduced topics list (compile-time constant)
    topics_list = topics_node.reduced()
    topic_values = [Expr(t, ctx).lower() for t in topics_list.elements]
    n_topics = len(topic_values)

    # Get data type
    data_typ = data_node._metadata["type"]

    if data_typ == BYTES32_T:
        # For bytes32: store to temp memory, then log from there
        tmp = ctx.new_internal_variable(BYTES32_T)
        data_val = Expr(data_node, ctx).lower()
        b.mstore(data_val, tmp)
        data_ptr = tmp
        data_len = IRLiteral(32)
    else:
        # For Bytes[N]: data starts at ptr+32, length at ptr
        data = Expr(data_node, ctx).lower()
        data_len = b.mload(data)
        data_ptr = b.add(data, IRLiteral(32))

    # Emit log instruction
    b.log(n_topics, data_ptr, data_len, *topic_values)

    return IRLiteral(0)  # Statement builtin, no return


def lower_raw_revert(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    raw_revert(data)

    Revert with custom data. This is a terminal operation.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    data = Expr(node.args[0], ctx).lower()

    # Get data pointer and length
    data_len = b.mload(data)
    data_ptr = b.add(data, IRLiteral(32))

    # Revert terminates execution
    b.revert(data_len, data_ptr)

    return IRLiteral(0)  # Unreachable


HANDLERS = {
    "raw_call": lower_raw_call,
    "send": lower_send,
    "raw_log": lower_raw_log,
    "raw_revert": lower_raw_revert,
}
