"""
System-level built-in functions for raw operations.

- raw_call(to, data, ...) - low-level external call
- send(to, value, gas=0) - send ether with optional gas stipend
- raw_log(topics, data) - low-level event emission
- raw_revert(data) - revert with custom data
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from vyper import ast as vy_ast
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import ArgumentException, StateAccessViolation
from vyper.semantics.types import BytesT, TupleT
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


def _is_msg_data(node) -> bool:
    """Check if node is msg.data attribute access."""
    return (
        isinstance(node, vy_ast.Attribute)
        and node.attr == "data"
        and isinstance(node.value, vy_ast.Name)
        and node.value.id == "msg"
    )


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


def lower_raw_call(node: vy_ast.Call, ctx: VenomCodegenContext) -> Union[IROperand, VyperValue]:
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
    to = Expr(node.args[0], ctx).lower_value()

    # Parse kwargs (need to know is_static before constancy check)
    max_outsize = _get_literal_kwarg(node, "max_outsize", 0)
    is_delegate = _get_literal_kwarg(node, "is_delegate_call", False)
    is_static = _get_literal_kwarg(node, "is_static_call", False)
    revert_on_failure = _get_literal_kwarg(node, "revert_on_failure", True)

    # Validate delegate/static mutual exclusivity
    if is_delegate and is_static:
        raise ArgumentException(
            "Call may use one of `is_delegate_call` or `is_static_call`, not both", node
        )

    # Validate value not passed with delegate/static
    # Check if value kwarg is explicitly provided (not relying on default)
    value_node = _get_kwarg_value(node, "value")
    if (is_delegate or is_static) and value_node is not None:
        raise ArgumentException("value= may not be passed for static or delegate calls!", node)

    # Check constancy: non-static calls are not allowed from view/pure functions
    if not is_static and ctx.is_constant():
        raise StateAccessViolation(
            f"Cannot make modifying calls from {ctx.pp_constancy()},"
            " use `is_static_call=True` to perform this action",
            node,
        )

    # Handle msg.data specially - it needs to copy calldata to memory
    # This must be done before other memory allocations to use msize correctly
    data_node = node.args[1]
    if _is_msg_data(data_node):
        # Get msize first - this is where we'll copy calldata
        data_ptr = b.msize()
        data_len = b.calldatasize()
        # Copy entire calldata to memory at msize
        b.calldatacopy(data_ptr, IRLiteral(0), data_len)
    else:
        data_vv = Expr(data_node, ctx).lower()
        data = ctx.unwrap(data_vv)  # Copies storage/transient to memory
        # Get input data pointer and length
        # Bytes layout: [32-byte length][data...]
        data_len = b.mload(data)
        data_ptr = b.add(data, IRLiteral(32))

    # Handle gas kwarg - defaults to remaining gas
    gas_node = _get_kwarg_value(node, "gas")
    gas: IROperand
    if gas_node is None:
        gas = b.gas()
    else:
        gas = Expr(gas_node, ctx).lower_value()

    # Handle value kwarg - only for regular call
    value_node = _get_kwarg_value(node, "value")
    value: IROperand
    if value_node is None:
        value = IRLiteral(0)
    else:
        value = Expr(value_node, ctx).lower_value()

    # Allocate output buffer if needed
    out_val: Optional["VyperValue"]
    out_ptr: IROperand
    if max_outsize > 0:
        out_val = ctx.new_temporary_value(BytesT(max_outsize))
        out_ptr = b.add(out_val.operand, IRLiteral(32))
    else:
        out_val = None
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
        # Propagate callee's revert reason (matches legacy check_external_call)
        fail_label = b.create_block("call_failed")
        ok_label = b.create_block("call_ok")
        b.jnz(success, ok_label.label, fail_label.label)

        b.append_block(fail_label)
        b.set_block(fail_label)
        ret_size = b.returndatasize()
        b.returndatacopy(IRLiteral(0), IRLiteral(0), ret_size)
        b.revert(IRLiteral(0), ret_size)

        b.append_block(ok_label)
        b.set_block(ok_label)

        if max_outsize > 0:
            # Store actual return size (capped at max_outsize)
            ret_size = b.returndatasize()
            # min(ret_size, max_outsize)
            capped = b.select(
                b.lt(ret_size, IRLiteral(max_outsize)), ret_size, IRLiteral(max_outsize)
            )
            assert out_val is not None
            ctx.ptr_store(out_val.ptr(), capped)
            return out_val
        # No return value (returns None in Vyper)
        return IRLiteral(0)
    else:
        if max_outsize > 0:
            # Store actual return size (capped at max_outsize)
            ret_size = b.returndatasize()
            capped = b.select(
                b.lt(ret_size, IRLiteral(max_outsize)), ret_size, IRLiteral(max_outsize)
            )
            assert out_val is not None
            ctx.ptr_store(out_val.ptr(), capped)

            # Return (success, data) tuple with inline bytes
            # Layout: [bool (32)][bytes_len (32)][bytes_data (ceil32(max_outsize))]
            bytes_t = BytesT(max_outsize)
            tuple_t = TupleT((UINT256_T, bytes_t))
            tuple_local = ctx.new_temporary_value(tuple_t)

            # Store success at offset 0
            ctx.ptr_store(tuple_local.ptr(), success)

            # Copy bytes (length + data) inline starting at offset 32
            # bytes_t.memory_bytes_required = 32 (length) + ceil32(max_outsize) (data)
            bytes_ptr = ctx.add_offset(tuple_local.ptr(), IRLiteral(32))
            ctx.copy_memory(bytes_ptr.operand, out_val.operand, bytes_t.memory_bytes_required)

            return tuple_local

        # Just return success flag
        return success


def lower_send(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    send(to, value, gas=0)

    Send ether to address. Reverts on failure.
    The gas kwarg defaults to 0 (empty gas stipend) in Vyper.
    """
    from vyper.codegen_venom.expr import Expr

    ctx.check_is_not_constant("send ether", node)

    b = ctx.builder

    to = Expr(node.args[0], ctx).lower_value()
    value = Expr(node.args[1], ctx).lower_value()

    # Parse gas kwarg (default 0)
    gas_node = _get_kwarg_value(node, "gas")
    gas: IROperand
    if gas_node is None:
        gas = IRLiteral(0)
    else:
        gas = Expr(gas_node, ctx).lower_value()

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

    ctx.check_is_not_constant("use raw_log", node)

    b = ctx.builder

    topics_node = node.args[0]
    data_node = node.args[1]

    # Get the reduced topics list (compile-time constant)
    topics_list = topics_node.reduced()
    topic_values = [Expr(t, ctx).lower_value() for t in topics_list.elements]
    n_topics = len(topic_values)

    # Get data type
    data_typ = data_node._metadata["type"]

    data_ptr: IROperand
    data_len: IROperand
    if data_typ == BYTES32_T:
        # For bytes32: store to temp memory, then log from there
        tmp_val = ctx.new_temporary_value(BYTES32_T)
        data_val = Expr(data_node, ctx).lower_value()
        ctx.ptr_store(tmp_val.ptr(), data_val)
        data_ptr = tmp_val.ptr().operand
        data_len = IRLiteral(32)
    else:
        # For Bytes[N]: data starts at ptr+32, length at ptr
        data_vv = Expr(data_node, ctx).lower()
        data = ctx.unwrap(data_vv)  # Copies storage/transient to memory
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

    data_vv = Expr(node.args[0], ctx).lower()
    data = ctx.unwrap(data_vv)  # Copies storage/transient to memory

    # Get data pointer and length
    data_len = b.mload(data)
    data_ptr = b.add(data, IRLiteral(32))

    # Revert terminates execution
    b.revert(data_ptr, data_len)

    return IRLiteral(0)  # Unreachable


def lower_selfdestruct(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    selfdestruct(to)

    Destroy the contract and send remaining balance to address.
    This is a terminal operation.

    Note: selfdestruct is deprecated and may have reduced functionality
    in future EVM upgrades. Warning is emitted during semantic analysis.
    """
    from vyper.codegen_venom.expr import Expr

    ctx.check_is_not_constant("selfdestruct", node)

    b = ctx.builder

    to = Expr(node.args[0], ctx).lower_value()
    b.selfdestruct(to)

    return IRLiteral(0)  # Unreachable


HANDLERS = {
    "raw_call": lower_raw_call,
    "send": lower_send,
    "raw_log": lower_raw_log,
    "raw_revert": lower_raw_revert,
    "selfdestruct": lower_selfdestruct,
}
