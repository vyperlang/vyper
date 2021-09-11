from vyper import ast as vy_ast
from vyper.exceptions import (
    StateAccessViolation,
    StructureException,
    TypeCheckFailure,
)
from vyper.old_codegen.abi import abi_encode, abi_type_of, lazy_abi_decode
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, unwrap_location
from vyper.old_codegen.types import TupleType, get_type_for_exact_size, canonicalize_type
import vyper.utils as util


def _pack_arguments(contract_sig, args, context, pos):
    # abi encoding just treats all args as a big tuple
    args_tuple_t = TupleType([x.typ for x in args])
    args_as_tuple = LLLnode.from_list(["multi"] + [x for x in args], typ=args_tuple_t)
    args_abi_t = abi_type_of(args_tuple_t)

    maxlen = args_abi_t.size_bound()
    maxlen += 32  # padding for the method id

    buf_t = get_type_for_exact_size(maxlen)
    buf = context.new_internal_variable(buf_t)

    args_ofst = buf + 28
    args_len = maxlen - 28

    abi_signature = contract_sig.name + canonicalize_type(args_tuple_t)

    # layout:
    # 32 bytes                 | args
    # 0x..00<method_id_4bytes> | args
    # the reason for the left padding is just so the alignment is easier.
    # if we were only targeting constantinople, we could align
    # to buf (and also keep code size small) by using
    # (mstore buf (shl signature.method_id 224))
    mstore_method_id = [["mstore", buf, util.abi_method_id(abi_signature)]]

    encode_args = abi_encode(buf, args_as_tuple, pos)

    return mstore_method_id + [encode_args], args_ofst, args_len


def _unpack_returndata(contract_sig, context, pos):
    return_t = abi_type_of(contract_sig.return_type)
    min_return_size = return_t.static_size()

    maxlen = return_t.size_bound()
    buf_t = get_type_for_exact_size(maxlen)
    buf = context.new_internal_variable(buf_t)
    ret_ofst = buf
    ret_len = maxlen

    # when return data is expected, revert when the length of `returndatasize` is insufficient
    ret = []
    if min_return_size > 0:
        ret += [["assert", ["gt", "returndatasize", min_return_size - 1]]]
    # TODO assert returndatasize <= maxlen

    # abi_decode has appropriate clampers for the individual members of the return type
    buf = LLLnode(buf, location="memory")
    ret += [lazy_abi_decode(contract_sig.return_type, buf, pos=pos)]

    return ret, ret_ofst, ret_len


def _external_call_helper(contract_address, contract_sig, args_lll, context, pos=None, value=None, gas=None):

    if value is None:
        value = 0
    if gas is None:
        gas = "gas"

    # sanity check
    assert len(contract_sig.args) == len(args_lll)

    if context.is_constant() and contract_sig.mutability not in ("view", "pure"):
        # TODO is this already done in type checker?
        raise StateAccessViolation(
            f"May not call state modifying function '{contract_sig.name}' "
            f"within {context.pp_constancy()}.",
            pos,
        )

    sub = ["seq"]

    arg_packer, args_ofst, args_len = _pack_arguments(contract_sig, args_lll, context, pos)
    ret_unpacker, ret_ofst, ret_len = _unpack_returndata(contract_sig, context, pos)

    sub += arg_packer

    if contract_sig.return_type is None:
        # if we do not expect return data, check that a contract exists at the target address
        # we can omit this when we _do_ expect return data because we later check `returndatasize`
        # CMC 20210907 do we need to check this before the call, or can we defer until after?
        # if we can defer, this code can be pushed down into unpack_returndata
        sub.append(["assert", ["extcodesize", contract_address]])

    if context.is_constant() or contract_sig.mutability in ("view", "pure"):
        call_op = ["staticcall", gas, contract_address, args_ofst, args_len, ret_ofst, ret_len]
    else:
        call_op = ["call", gas, contract_address, value, args_ofst, args_len, ret_ofst, ret_len]

    sub.append(["assert", call_op])

    if contract_sig.return_type is not None:
        sub += ret_unpacker

    return LLLnode.from_list(sub, typ=contract_sig.return_type, location="memory", pos=pos)


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
        assert stmt_expr.func.value.id == "self"

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

    return _external_call_helper(
        contract_address, contract_sig, args_lll, context, pos, value=value, gas=gas,
    )
