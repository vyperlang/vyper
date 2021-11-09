import vyper.utils as util
from vyper import ast as vy_ast
from vyper.exceptions import StateAccessViolation, StructureException, TypeCheckFailure
from vyper.old_codegen.abi import abi_encode, abi_type_of
from vyper.old_codegen.lll_node import Encoding, LLLnode
from vyper.old_codegen.parser_utils import (
    calculate_type_for_external_return,
    check_external_call,
    get_element_ptr,
    getpos,
    unwrap_location,
)
from vyper.old_codegen.types import TupleType, canonicalize_type, get_type_for_exact_size
from vyper.old_codegen.types.check import check_assign


def _pack_arguments(contract_sig, args, context, pos):
    # abi encoding just treats all args as a big tuple
    args_tuple_t = TupleType([x.typ for x in args])
    args_as_tuple = LLLnode.from_list(["multi"] + [x for x in args], typ=args_tuple_t)
    args_abi_t = abi_type_of(args_tuple_t)

    # sanity typecheck - make sure the arguments can be assigned
    dst_tuple_t = TupleType([arg.typ for arg in contract_sig.args][: len(args)])
    _tmp = LLLnode("fake node", location="memory", typ=dst_tuple_t)
    check_assign(_tmp, args_as_tuple, pos)

    if contract_sig.return_type is not None:
        return_abi_t = abi_type_of(calculate_type_for_external_return(contract_sig.return_type))

        # we use the same buffer for args and returndata,
        # so allocate enough space here for the returndata too.
        buflen = max(args_abi_t.size_bound(), return_abi_t.size_bound())
    else:
        buflen = args_abi_t.size_bound()

    buflen += 32  # padding for the method id

    buf_t = get_type_for_exact_size(buflen)
    buf = context.new_internal_variable(buf_t)

    args_ofst = buf + 28
    args_len = args_abi_t.size_bound() + 4

    abi_signature = contract_sig.name + canonicalize_type(dst_tuple_t)

    # layout:
    # 32 bytes                 | args
    # 0x..00<method_id_4bytes> | args
    # the reason for the left padding is just so the alignment is easier.
    # if we were only targeting constantinople, we could align
    # to buf (and also keep code size small) by using
    # (mstore buf (shl signature.method_id 224))
    mstore_method_id = [["mstore", buf, util.abi_method_id(abi_signature)]]

    if len(args) == 0:
        encode_args = ["pass"]
    else:
        encode_args = abi_encode(buf + 32, args_as_tuple, pos)

    return buf, mstore_method_id + [encode_args], args_ofst, args_len


def _returndata_encoding(contract_sig):
    if contract_sig.is_from_json:
        return Encoding.JSON_ABI
    return Encoding.ABI


def _unpack_returndata(buf, contract_sig, context, pos):
    return_t = contract_sig.return_type
    if return_t is None:
        return ["pass"], 0, 0

    return_t = calculate_type_for_external_return(return_t)
    # if the abi signature has a different type than
    # the vyper type, we need to wrap and unwrap the type
    # so that the ABI decoding works correctly
    should_unwrap_abi_tuple = return_t != contract_sig.return_type

    abi_return_t = abi_type_of(return_t)

    min_return_size = abi_return_t.min_size()
    max_return_size = abi_return_t.size_bound()
    assert 0 < min_return_size <= max_return_size

    ret_ofst = buf
    ret_len = max_return_size

    # revert when returndatasize is not in bounds
    ret = []
    # runtime: min_return_size <= returndatasize
    # TODO move the -1 optimization to LLL optimizer
    ret += [["assert", ["gt", "returndatasize", min_return_size - 1]]]

    # add as the last LLLnode a pointer to the return data structure

    # the return type has been wrapped by the calling contract;
    # unwrap it so downstream code isn't confused.
    # basically this expands to buf+32 if the return type has been wrapped
    # in a tuple AND its ABI type is dynamic.
    # in most cases, this simply will evaluate to ret.
    # in the special case where the return type has been wrapped
    # in a tuple AND its ABI type is dynamic, it expands to buf+32.
    buf = LLLnode(buf, typ=return_t, encoding=_returndata_encoding(contract_sig), location="memory")

    if should_unwrap_abi_tuple:
        buf = get_element_ptr(buf, 0, pos=None, array_bounds_check=False)

    ret += [buf]

    return ret, ret_ofst, ret_len


def _external_call_helper(
    contract_address, contract_sig, args_lll, context, pos=None, value=None, gas=None
):

    if value is None:
        value = 0
    if gas is None:
        gas = "gas"

    # sanity check
    assert len(contract_sig.base_args) <= len(args_lll) <= len(contract_sig.args)

    if context.is_constant() and contract_sig.mutability not in ("view", "pure"):
        # TODO is this already done in type checker?
        raise StateAccessViolation(
            f"May not call state modifying function '{contract_sig.name}' "
            f"within {context.pp_constancy()}.",
            pos,
        )

    sub = ["seq"]

    buf, arg_packer, args_ofst, args_len = _pack_arguments(contract_sig, args_lll, context, pos)

    ret_unpacker, ret_ofst, ret_len = _unpack_returndata(buf, contract_sig, context, pos)

    sub += arg_packer

    if contract_sig.return_type is None:
        # if we do not expect return data, check that a contract exists at the
        # target address. we must perform this check BEFORE the call because
        # the contract might selfdestruct. on the other hand we can omit this
        # when we _do_ expect return data because we later check
        # `returndatasize` (that check works even if the contract
        # selfdestructs).
        sub.append(["assert", ["extcodesize", contract_address]])

    if context.is_constant() or contract_sig.mutability in ("view", "pure"):
        call_op = ["staticcall", gas, contract_address, args_ofst, args_len, ret_ofst, ret_len]
    else:
        call_op = ["call", gas, contract_address, value, args_ofst, args_len, ret_ofst, ret_len]

    sub.append(check_external_call(call_op))

    if contract_sig.return_type is not None:
        sub += ret_unpacker

    ret = LLLnode.from_list(
        # set the encoding to ABI here, downstream code will decode and add clampers.
        sub,
        typ=contract_sig.return_type,
        location="memory",
        encoding=_returndata_encoding(contract_sig),
        pos=pos,
    )

    return ret


# TODO push me up to expr.py
def get_gas_and_value(stmt_expr, context):
    from vyper.old_codegen.expr import Expr  # TODO rethink this circular import

    value, gas = None, None
    for kw in stmt_expr.keywords:
        if kw.arg == "gas":
            gas = Expr.parse_value_expr(kw.value, context)
        elif kw.arg == "value":
            value = Expr.parse_value_expr(kw.value, context)
        else:
            raise TypeCheckFailure("Unexpected keyword argument")
    return value, gas


def lll_for_external_call(stmt_expr, context):
    from vyper.old_codegen.expr import Expr  # TODO rethink this circular import

    pos = getpos(stmt_expr)
    value, gas = get_gas_and_value(stmt_expr, context)
    args_lll = [Expr(x, context).lll_node for x in stmt_expr.args]

    if isinstance(stmt_expr.func, vy_ast.Attribute) and isinstance(
        stmt_expr.func.value, vy_ast.Call
    ):
        # e.g. `Foo(address).bar()`

        # sanity check
        assert len(stmt_expr.func.value.args) == 1
        contract_name = stmt_expr.func.value.func.id
        contract_address = Expr.parse_value_expr(stmt_expr.func.value.args[0], context)

    elif (
        isinstance(stmt_expr.func.value, vy_ast.Attribute)
        and stmt_expr.func.value.attr in context.globals
        # TODO check for self?
        and hasattr(context.globals[stmt_expr.func.value.attr].typ, "name")
    ):
        # e.g. `self.foo.bar()`

        # sanity check
        assert stmt_expr.func.value.value.id == "self", stmt_expr

        contract_name = context.globals[stmt_expr.func.value.attr].typ.name
        type_ = stmt_expr.func.value._metadata["type"]
        var = context.globals[stmt_expr.func.value.attr]
        contract_address = unwrap_location(
            LLLnode.from_list(
                type_.position.position,
                typ=var.typ,
                location="storage",
                pos=pos,
                annotation="self." + stmt_expr.func.value.attr,
            )
        )
    else:
        # TODO catch this during type checking
        raise StructureException("Unsupported operator.", stmt_expr)

    method_name = stmt_expr.func.attr
    contract_sig = context.sigs[contract_name][method_name]

    ret = _external_call_helper(
        contract_address,
        contract_sig,
        args_lll,
        context,
        pos,
        value=value,
        gas=gas,
    )
    ret.annotation = stmt_expr.get("node_source_code")

    return ret
