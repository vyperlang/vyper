"""
System-level built-in functions for raw operations.

- raw_call(to, data, ...) - low-level external call
- send(to, value, gas=0) - send ether with optional gas stipend
- raw_log(topics, data) - low-level event emission
- raw_revert(data) - revert with custom data
"""

from __future__ import annotations

from typing import Optional, Union

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._kwargs import BuiltinCall, get_bool_kwarg, get_literal_kwarg
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import ArgumentException, StateAccessViolation
from vyper.semantics.types import BytesT, TupleT
from vyper.semantics.types.shortcuts import BYTES32_T, UINT256_T
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

_RAW_CALL_KWARGS = (
    "max_outsize",
    "gas",
    "value",
    "is_delegate_call",
    "is_static_call",
    "revert_on_failure",
)
_SEND_KWARGS = ("gas",)


def _is_msg_data(node) -> bool:
    """Check if node is msg.data attribute access."""
    return (
        isinstance(node, vy_ast.Attribute)
        and node.attr == "data"
        and isinstance(node.value, vy_ast.Name)
        and node.value.id == "msg"
    )


def lower_raw_call(call: BuiltinCall) -> Union[IROperand, VyperValue]:
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
    node = call.node
    ctx = call.ctx
    b = ctx.builder

    # Parse kwargs (need to know is_static before constancy check)
    call.validate_kwargs(_RAW_CALL_KWARGS)
    kwarg_constants = call.get_kwarg_ast_constants(
        {
            "max_outsize": 0,
            "is_delegate_call": False,
            "is_static_call": False,
            "revert_on_failure": True,
        }
    )
    max_outsize = get_literal_kwarg(kwarg_constants, "max_outsize")
    is_delegate = get_bool_kwarg(kwarg_constants, "is_delegate_call")
    is_static = get_bool_kwarg(kwarg_constants, "is_static_call")
    revert_on_failure = get_bool_kwarg(kwarg_constants, "revert_on_failure")

    # Validate delegate/static mutual exclusivity
    if is_delegate and is_static:
        raise ArgumentException(
            "Call may use one of `is_delegate_call` or `is_static_call`, not both", node
        )

    # Validate value not passed with delegate/static
    # Check if value kwarg is explicitly provided (not relying on default)
    value_is_provided = call.kwarg_is_provided("value")
    if (is_delegate or is_static) and value_is_provided:
        raise ArgumentException("value= may not be passed for static or delegate calls!", node)

    # Check constancy: non-static calls are not allowed from view/pure functions
    if not is_static and ctx.is_constant():
        raise StateAccessViolation(
            f"Cannot make modifying calls from {ctx.pp_constancy()},"
            " use `is_static_call=True` to perform this action",
            node,
        )

    # Parse positional args
    to = call.lower_pos_arg_values(node.args[:1])[0]

    # Evaluate data argument
    data_node = node.args[1]
    use_msg_data = _is_msg_data(data_node)
    if not use_msg_data:
        data_vv = call.lower_pos_args((data_node,))[0]
        data = ctx.unwrap(data_vv)  # Copies storage/transient to memory
        # Bytes layout: [32-byte length][data...]
        assert isinstance(data, IRVariable)
        data_len = b.mload(data)
        data_ptr = b.add(data, IRLiteral(32))

    runtime_kwargs = call.get_kwarg_values({"gas": b.gas, "value": IRLiteral(0)})
    gas = runtime_kwargs["gas"]
    value = runtime_kwargs["value"]

    # Allocate output buffer if needed
    out_val: Optional["VyperValue"]
    out_ptr: IROperand
    if max_outsize > 0:
        out_val = ctx.new_temporary_value(BytesT(max_outsize))
        out_ptr = b.add(out_val.operand, IRLiteral(32))
    else:
        out_val = None
        out_ptr = ctx.allocate_buffer(0)._ptr

    # Copy msg.data to scratch AFTER all kwarg evaluation, so nothing
    # else overwrites the memtop scratch region before the call.
    if use_msg_data:
        data_ptr = ctx.allocate_dyn()
        data_len = b.calldatasize()
        b.calldatacopy(data_ptr, IRLiteral(0), data_len)

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
        revert_buffer = ctx.allocate_buffer(0, annotation="lower raw call revert on failure buffer")
        b.returndatacopy(revert_buffer._ptr, IRLiteral(0), ret_size)
        b.revert(revert_buffer._ptr, ret_size)

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
            assert isinstance(bytes_ptr.operand, IRVariable)
            ctx.copy_memory(bytes_ptr.operand, out_val.operand, bytes_t.memory_bytes_required)

            return tuple_local

        # Just return success flag
        return success


def lower_send(call: BuiltinCall) -> IROperand:
    """
    send(to, value, gas=0)

    Send ether to address. Reverts on failure.
    The gas kwarg defaults to 0 (empty gas stipend) in Vyper.
    """
    node = call.node
    ctx = call.ctx
    ctx.check_is_not_constant("send ether", node)

    b = ctx.builder

    to, value = call.lower_pos_arg_values()

    call.validate_kwargs(_SEND_KWARGS)
    runtime_kwargs = call.get_kwarg_values({"gas": IRLiteral(0)})
    gas = runtime_kwargs["gas"]

    argsptr_buf = ctx.allocate_buffer(0, annotation="lower send args buffer")
    retptr_buf = ctx.allocate_buffer(0, annotation="lower send retptr buffer")
    # call(gas, to, value, 0, 0, 0, 0)
    success = b.call(
        gas,
        to,
        value,
        argsptr_buf._ptr,  # No input data
        IRLiteral(0),
        retptr_buf._ptr,  # No output
        IRLiteral(0),
    )

    # send() asserts success
    b.assert_(success)

    return IRLiteral(0)  # Statement builtin, no return


def lower_raw_log(call: BuiltinCall) -> IROperand:
    """
    raw_log(topics, data)

    Emit a raw log with 0-4 topics.
    - topics: list of bytes32 values (compile-time fixed length)
    - data: bytes32 or Bytes[N]
    """
    from vyper.codegen_venom.expr import Expr

    node = call.node
    ctx = call.ctx
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
        assert isinstance(data, IRVariable)
        data_len = b.mload(data)
        data_ptr = b.add(data, IRLiteral(32))

    # Emit log instruction
    assert isinstance(data_ptr, IRVariable)
    b.log(n_topics, data_ptr, data_len, *topic_values)

    return IRLiteral(0)  # Statement builtin, no return


def lower_raw_revert(call: BuiltinCall) -> IROperand:
    """
    raw_revert(data)

    Revert with custom data. This is a terminal operation.
    """
    from vyper.codegen_venom.expr import Expr

    node = call.node
    ctx = call.ctx
    b = ctx.builder

    data_vv = Expr(node.args[0], ctx).lower()
    data = ctx.unwrap(data_vv)  # Copies storage/transient to memory

    # Get data pointer and length
    assert isinstance(data, IRVariable)
    data_len = b.mload(data)
    data_ptr = b.add(data, IRLiteral(32))

    # Revert terminates execution
    b.revert(data_ptr, data_len)

    return IRLiteral(0)  # Unreachable


def lower_selfdestruct(call: BuiltinCall) -> IROperand:
    """
    selfdestruct(to)

    Destroy the contract and send remaining balance to address.
    This is a terminal operation.

    Note: selfdestruct is deprecated and may have reduced functionality
    in future EVM upgrades. Warning is emitted during semantic analysis.
    """
    from vyper.codegen_venom.expr import Expr

    node = call.node
    ctx = call.ctx
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
