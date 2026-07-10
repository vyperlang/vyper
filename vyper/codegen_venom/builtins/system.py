"""
System-level built-in functions for raw operations.

- raw_call(to, data, ...) - low-level external call
- send(to, value, gas=0) - send ether with optional gas stipend
- raw_log(topics, data) - low-level event emission
- raw_revert(data) - revert with custom data
"""

from __future__ import annotations

from typing import Optional, Union

from vyper.codegen_venom.builtins._call import BuiltinLowerer, PreparedBuiltinCall
from vyper.codegen_venom.call_args import VALUE_LIST, DataView, DataViewKind, data_source
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import ArgumentException, StateAccessViolation
from vyper.semantics.types import BytesT, TupleT
from vyper.semantics.types.shortcuts import BYTES32_T
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable


def lower_raw_call(call: PreparedBuiltinCall) -> Union[IROperand, VyperValue]:
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

    max_outsize = call.literal("max_outsize")
    is_delegate = call.literal("is_delegate_call")
    is_static = call.literal("is_static_call")
    revert_on_failure = call.literal("revert_on_failure")

    # Validate delegate/static mutual exclusivity
    if is_delegate and is_static:
        raise ArgumentException(
            "Call may use one of `is_delegate_call` or `is_static_call`, not both", node
        )

    # Validate value not passed with delegate/static
    if (is_delegate or is_static) and call.was_provided("value"):
        raise ArgumentException("value= may not be passed for static or delegate calls!", node)

    # Check constancy: non-static calls are not allowed from view/pure functions
    if not is_static and ctx.is_constant():
        raise StateAccessViolation(
            f"Cannot make modifying calls from {ctx.pp_constancy()},"
            " use `is_static_call=True` to perform this action",
            node,
        )

    to = call.word("to")

    source = call.data_source("data")
    if isinstance(source, DataView):
        use_msg_data = True
    else:
        use_msg_data = False
        data = source.operand
        # Bytes layout: [32-byte length][data...]
        assert isinstance(data, IRVariable)
        data_len = b.mload(data)
        data_ptr = b.add(data, IRLiteral(32))

    gas = call.kwarg_value("gas")
    value = call.kwarg_value("value")

    # Allocate output buffer if needed
    out_val: Optional["VyperValue"]
    out_ptr: IROperand
    if max_outsize > 0:
        out_val = ctx.new_temporary_value(BytesT(max_outsize))
        out_ptr = b.add(out_val.operand, IRLiteral(32))
    else:
        out_val = None
        out_ptr = ctx.allocate_buffer(0)._ptr

    # calldatasize must be computed before allocate_scratch, since the
    # allocation is runtime-sized now. The copy stays after all kwarg
    # evaluation, preserving the instruction order of the previous
    # memtop (MSIZE-based) lowering, where the scratch region was
    # genuinely unreserved and the copy had to be last; with a tracked
    # `dalloca` buffer the ordering is no longer load-bearing, it is
    # kept only to avoid disturbing generated code.
    if use_msg_data:
        data_len = b.calldatasize()
        data_ptr = ctx.allocate_scratch(data_len)
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
            tuple_t = call.return_type
            assert isinstance(tuple_t, TupleT)
            bytes_t = tuple_t.member_types[1]
            assert isinstance(bytes_t, BytesT)
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


def lower_send(call: PreparedBuiltinCall) -> IROperand:
    """
    send(to, value, gas=0)

    Send ether to address. Reverts on failure.
    The gas kwarg defaults to 0 (empty gas stipend) in Vyper.
    """
    node = call.node
    ctx = call.ctx
    ctx.check_is_not_constant("send ether", node)

    b = ctx.builder

    to = call.word("to")
    value = call.word("value")
    gas = call.kwarg_value("gas")

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


def lower_raw_log(call: PreparedBuiltinCall) -> IROperand:
    """
    raw_log(topics, data)

    Emit a raw log with 0-4 topics.
    - topics: list of bytes32 values (compile-time fixed length)
    - data: bytes32 or Bytes[N]
    """
    node = call.node
    ctx = call.ctx
    ctx.check_is_not_constant("use raw_log", node)

    b = ctx.builder

    topic_values = [topic.word() for topic in call.value_list("topics")]
    n_topics = len(topic_values)

    data_typ = call.arg_type("data")

    data_ptr: IROperand
    data_len: IROperand
    if data_typ == BYTES32_T:
        # For bytes32: store to temp memory, then log from there
        tmp_val = ctx.new_temporary_value(BYTES32_T)
        data_val = call.word("data")
        ctx.ptr_store(tmp_val.ptr(), data_val)
        data_ptr = tmp_val.ptr().operand
        data_len = IRLiteral(32)
    else:
        # For Bytes[N]: data starts at ptr+32, length at ptr
        data = call.memory("data")
        data_len = b.mload(data)
        data_ptr = b.add(data, IRLiteral(32))

    # Emit log instruction
    assert isinstance(data_ptr, IRVariable)
    b.log(n_topics, data_ptr, data_len, *topic_values)

    return IRLiteral(0)  # Statement builtin, no return


def lower_raw_revert(call: PreparedBuiltinCall) -> IROperand:
    """
    raw_revert(data)

    Revert with custom data. This is a terminal operation.
    """
    ctx = call.ctx
    b = ctx.builder

    data = call.memory("data")

    # Get data pointer and length
    assert isinstance(data, IRVariable)
    data_len = b.mload(data)
    data_ptr = b.add(data, IRLiteral(32))

    # Revert terminates execution
    b.revert(data_ptr, data_len)

    return IRLiteral(0)  # Unreachable


def lower_selfdestruct(call: PreparedBuiltinCall) -> IROperand:
    """
    selfdestruct(to)

    Destroy the contract and send remaining balance to address.
    This is a terminal operation.

    Note: selfdestruct is deprecated and may have reduced functionality
    in future EVM upgrades. Warning is emitted during semantic analysis.
    """
    node = call.node
    ctx = call.ctx
    ctx.check_is_not_constant("selfdestruct", node)

    b = ctx.builder

    to = call.word("to")
    b.selfdestruct(to)

    return IRLiteral(0)  # Unreachable


HANDLERS = {
    "raw_call": BuiltinLowerer(
        lower_raw_call,
        arg_policies={
            "data": data_source(
                DataViewKind.CALLDATA, unsupported_message="unsupported raw_call payload"
            )
        },
    ),
    "send": BuiltinLowerer(lower_send),
    "raw_log": BuiltinLowerer(lower_raw_log, arg_policies={"topics": VALUE_LIST}),
    "raw_revert": BuiltinLowerer(lower_raw_revert),
    "selfdestruct": BuiltinLowerer(lower_selfdestruct),
}
