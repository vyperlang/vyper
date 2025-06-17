import copy
from dataclasses import dataclass

import vyper.utils as util
from vyper.codegen.abi_encoder import abi_encode
from vyper.codegen.core import (
    _freshname,
    add_ofst,
    calculate_type_for_external_return,
    check_assign,
    check_external_call,
    dummy_node_for_type,
    eval_once_check,
    get_type_for_exact_size,
    make_setter,
    needs_clamp,
    unwrap_location,
    wrap_value_for_external_return,
)
from vyper.codegen.ir_node import Encoding, IRnode
from vyper.evm.address_space import MEMORY
from vyper.exceptions import TypeCheckFailure
from vyper.semantics.types import InterfaceT, TupleT
from vyper.semantics.types.function import StateMutability


@dataclass
class _CallKwargs:
    value: IRnode
    gas: IRnode
    skip_contract_check: bool
    default_return_value: IRnode


def _pack_arguments(fn_type, args, context):
    # abi encoding just treats all args as a big tuple
    args_tuple_t = TupleT([x.typ for x in args])
    args_as_tuple = IRnode.from_list(["multi"] + [x for x in args], typ=args_tuple_t)
    args_abi_t = args_tuple_t.abi_type

    # sanity typecheck - make sure the arguments can be assigned
    dst_tuple_t = TupleT(fn_type.argument_types[: len(args)])
    check_assign(dummy_node_for_type(dst_tuple_t), args_as_tuple)

    if fn_type.return_type is not None:
        return_abi_t = calculate_type_for_external_return(fn_type.return_type).abi_type

        # we use the same buffer for args and returndata,
        # so allocate enough space here for the returndata too.
        buflen = max(args_abi_t.size_bound(), return_abi_t.size_bound())
    else:
        buflen = args_abi_t.size_bound()

    buflen += 32  # padding for the method id

    buf_t = get_type_for_exact_size(buflen)
    buf = context.new_internal_variable(buf_t)

    args_ofst = add_ofst(buf, 28)
    args_len = args_abi_t.size_bound() + 4

    abi_signature = fn_type.name + dst_tuple_t.abi_type.selector_name()

    # layout:
    # 32 bytes                 | args
    # 0x..00<method_id_4bytes> | args
    # the reason for the left padding is just so the alignment is easier.
    # XXX: we could align to buf (and also keep code size small) by using
    # (mstore buf (shl signature.method_id 224))
    pack_args = ["seq"]
    pack_args.append(["mstore", buf, util.method_id_int(abi_signature)])

    if len(args) != 0:
        encode_buf = add_ofst(buf, 32)
        encode_buflen = buflen - 32
        pack_args.append(abi_encode(encode_buf, args_as_tuple, context, bufsz=encode_buflen))

    return buf, pack_args, args_ofst, args_len


def _unpack_returndata(buf, fn_type, call_kwargs, contract_address, context, expr):
    return_t = fn_type.return_type

    if return_t is None:
        return ["pass"], 0, 0

    wrapped_return_t = calculate_type_for_external_return(return_t)

    abi_return_t = wrapped_return_t.abi_type

    min_return_size = abi_return_t.static_size()
    max_return_size = abi_return_t.size_bound()
    assert 0 < min_return_size <= max_return_size

    ret_ofst = buf
    ret_len = max_return_size

    encoding = Encoding.ABI

    assert buf.location == MEMORY
    buf = copy.copy(buf)
    buf.typ = wrapped_return_t
    buf.encoding = encoding
    buf.annotation = f"{expr.node_source_code} returndata buffer"

    unpacker = ["seq"]

    assert isinstance(wrapped_return_t, TupleT)

    # unpack strictly
    if not needs_clamp(wrapped_return_t, encoding):
        # revert when returndatasize is not in bounds
        # NOTE: there is an optimization here: when needs_clamp is True,
        # make_setter (implicitly) checks returndatasize during abi
        # decoding.
        # since make_setter is not called in this branch, we need to check
        # returndatasize here, but we avoid a redundant check by only doing
        # the returndatasize check inside of this branch (and not in the
        # `needs_clamp==True` branch).
        # in the future, this check could be moved outside of the branch, and
        # instead rely on the optimizer to optimize out the redundant check,
        # it would need the optimizer to do algebraic reductions (along the
        # lines of `a>b and b>c and a>c` reduced to `a>b and b>c`).
        # another thing we could do instead once we have the machinery is to
        # simply always use make_setter instead of having this assertion, and
        # rely on memory analyser to optimize out the memory movement.
        assertion = IRnode.from_list(
            ["assert", ["ge", "returndatasize", min_return_size]],
            error_msg="returndatasize too small",
        )
        unpacker.append(assertion)

        return_buf = buf
    else:
        return_buf = context.new_internal_variable(wrapped_return_t)

        # note: make_setter does ABI decoding and clamps
        payload_bound = IRnode.from_list(
            ["select", ["lt", ret_len, "returndatasize"], ret_len, "returndatasize"]
        )
        with payload_bound.cache_when_complex("payload_bound") as (b1, payload_bound):
            unpacker.append(
                b1.resolve(make_setter(return_buf, buf, hi=add_ofst(buf, payload_bound)))
            )

    if call_kwargs.default_return_value is not None:
        # if returndatasize == 0:
        #    copy return override to buf
        # else:
        #    do the other stuff

        override_value = wrap_value_for_external_return(call_kwargs.default_return_value)
        stomp_return_buffer = ["seq"]
        if not call_kwargs.skip_contract_check:
            stomp_return_buffer.append(_extcodesize_check(contract_address))
        stomp_return_buffer.append(make_setter(return_buf, override_value))
        unpacker = ["if", ["eq", "returndatasize", 0], stomp_return_buffer, unpacker]

    unpacker = ["seq", unpacker, return_buf]

    return unpacker, ret_ofst, ret_len


def _parse_kwargs(call_expr, context):
    from vyper.codegen.expr import Expr  # TODO rethink this circular import

    def _bool(x):
        assert x.value in (0, 1), "type checker missed this"
        return bool(x.value)

    # note: codegen for kwarg values in AST order
    call_kwargs = {kw.arg: Expr(kw.value, context).ir_node for kw in call_expr.keywords}

    ret = _CallKwargs(
        value=unwrap_location(call_kwargs.pop("value", IRnode(0))),
        gas=unwrap_location(call_kwargs.pop("gas", IRnode("gas"))),
        skip_contract_check=_bool(call_kwargs.pop("skip_contract_check", IRnode(0))),
        default_return_value=call_kwargs.pop("default_return_value", None),
    )

    if len(call_kwargs) != 0:  # pragma: nocover
        raise TypeCheckFailure(f"Unexpected keyword arguments: {call_kwargs}")

    return ret


def _extcodesize_check(address):
    return IRnode.from_list(["assert", ["extcodesize", address]], error_msg="extcodesize is zero")


def _external_call_helper(contract_address, args_ir, call_kwargs, call_expr, context):
    fn_type = call_expr.func._metadata["type"]

    # sanity check
    assert fn_type.n_positional_args <= len(args_ir) <= fn_type.n_total_args

    ret = ["seq"]

    # this is a sanity check to prevent double evaluation of the external call
    # in the codegen pipeline. if the external call gets doubly evaluated,
    # a duplicate label exception will get thrown during assembly.
    ret.append(eval_once_check(_freshname(call_expr.node_source_code)))

    buf, arg_packer, args_ofst, args_len = _pack_arguments(fn_type, args_ir, context)

    ret_unpacker, ret_ofst, ret_len = _unpack_returndata(
        buf, fn_type, call_kwargs, contract_address, context, call_expr
    )

    ret += arg_packer

    if fn_type.return_type is None and not call_kwargs.skip_contract_check:
        # if we do not expect return data, check that a contract exists at the
        # target address. we must perform this check BEFORE the call because
        # the contract might selfdestruct. on the other hand we can omit this
        # when we _do_ expect return data because we later check
        # `returndatasize` (that check works even if the contract
        # selfdestructs).
        ret.append(_extcodesize_check(contract_address))

    gas = call_kwargs.gas
    value = call_kwargs.value

    use_staticcall = fn_type.mutability in (StateMutability.VIEW, StateMutability.PURE)
    if context.is_constant():
        assert use_staticcall, "typechecker missed this"

    if use_staticcall:
        call_op = ["staticcall", gas, contract_address, args_ofst, args_len, buf, ret_len]
    else:
        call_op = ["call", gas, contract_address, value, args_ofst, args_len, buf, ret_len]

    ret.append(check_external_call(call_op))

    return_t = fn_type.return_type
    if return_t is not None:
        ret.append(ret_unpacker)

    return IRnode.from_list(ret, typ=return_t, location=MEMORY)


def ir_for_external_call(call_expr, context):
    from vyper.codegen.expr import Expr  # TODO rethink this circular import

    contract_address = Expr.parse_value_expr(call_expr.func.value, context)
    assert isinstance(contract_address.typ, InterfaceT)
    args_ir = [Expr(x, context).ir_node for x in call_expr.args]
    call_kwargs = _parse_kwargs(call_expr, context)

    with contract_address.cache_when_complex("external_contract") as (b1, contract_address):
        return b1.resolve(
            _external_call_helper(contract_address, args_ir, call_kwargs, call_expr, context)
        )
