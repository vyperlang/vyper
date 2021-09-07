from vyper import ast as vy_ast
from vyper.exceptions import (
    StateAccessViolation,
    StructureException,
    TypeCheckFailure,
)
from vyper.old_codegen.abi import abi_encode, abi_decode, abi_type_of
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import (
    getpos,
    pack_arguments,
    unwrap_location,
)
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    TupleLike,
    get_size_of_type,
    get_static_size_of_type,
    has_dynamic_data,
)

def pack_arguments(sig, args, buf):
    # abi encoding just treats all args as a big tuple
    args_tuple_t = TupleType([x.typ for x in args])
    args_as_tuple = LLLnode.from_list(["multi"] + [x for x in args], typ=args_tuple_t)
    args_abi_t = abi_type_of(args_tuple_t)

    maxlen = args_abi_t.size_bound()
    maxlen += 32  # padding for the method id

    buf_t  = ByteArrayType(maxlen=maxlen)
    buf    = context.new_internal_variable(buf_t)

    args_ofst = buf    + 28
    args_len  = maxlen - 28

    # layout:
    # 32 bytes                 | args
    # 0x..00<method_id_4bytes> | args
    # the reason for the left padding is just so the alignment is easier.
    # if we were only targeting constantinople, we could align
    # to buf (and also keep code size small) by using
    # (mstore buf (shl signature.method_id 224))
    mstore_method_id = [["mstore", buf, sig.method_id]]

    encode_args = abi_encode(buf, args_as_tuple, pos)

    return mstore_method_id + [encode_args], args_ofst, args_len

def unpack_returndata(sig, context):
    return_t = abi_type_of(sig.output_type)
    min_return_size = return_t.static_size()

    maxlen = return_t.size_bound()
    buf_t  = ByteArrayType(maxlen=maxlen)
    buf    = context.new_internal_variable(buf_t)
    ret_ofst = buf
    ret_len  = maxlen

    # when return data is expected, revert when the length of `returndatasize` is insufficient
    ret = [["assert", ["gt", "returndatasize", min_return_size - 1]]]
    # TODO assert returndatasize <= maxlen

    # abi_decode has appropriate clampers for the individual members of the return type
    ret += [abi_decode_lazy(buf)]

    return ret, ret_ofst, ret_len


@type_check_wrapper
def external_call(node, context, interface_name, contract_address, value=None, gas=None):
    method_name = node.func.attr
    sig = context.sigs[interface_name][method_name]

    if value is None:
        value = 0
    if gas is None:
        gas = "gas"

    # sanity check
    if len(signature.args) != len(args):
        return

    if context.is_constant() and sig.mutability not in ("view", "pure"):
        # TODO is this already done in type checker?
        raise StateAccessViolation(
            f"May not call state modifying function '{method_name}' "
            f"within {context.pp_constancy()}.",
            node,
        )

    sub = ["seq"]

    arg_packer, args_ofst, args_len = pack_arguments(sig, args, context)
    ret_unpacker, ret_ofst, ret_len = unpack_arguments(sig, context)

    sub += arg_packer

    if sig.return_type is None:
        # if we do not expect return data, check that a contract exists at the target address
        # we can omit this when we _do_ expect return data because we later check `returndatasize`
        # CMC 20210907 do we need to check this before the call, or can we defer until after?
        # if we can defer, this code can be pushed down into unpack_returndata
        sub.append(["assert", ["extcodesize", contract_address]])

    if context.is_constant() or sig.mutability in ("view", "pure"):
        call_op = ["staticcall", gas, contract_address, args_ofst, args_len, ret_ofst, ret_len]
    else:
        call_op = ["call", gas, contract_address, value, args_ofst, args_len, ret_ofst, ret_len]

    sub.append(["assert", call_op])

    if sig.return_type is not None:
        sub += ret_unpacker

    return LLLnode.from_list(sub, typ=sig.return_type, location="memory", pos=getpos(node))


# TODO push me up to expr.py
def get_gas_and_value(stmt_expr, context):
    # circular import!
    from vyper.old_codegen.expr import Expr

    value, gas = None, None
    for kw in stmt_expr.keywords:
        if kw.arg == "gas":
            gas = Expr.parse_value_expr(kw.value, context)
        elif kw.arg == "value":
            value = Expr.parse_value_expr(kw.value, context)
        else:
            raise TypeCheckFailure("Unexpected keyword argument")
    return value, gas


def make_external_call(stmt_expr, context):
    value, gas = get_gas_and_value(stmt_expr, context)

    if isinstance(stmt_expr.func, vy_ast.Attribute) and isinstance(
        stmt_expr.func.value, vy_ast.Call
    ):
        # e.g. `Foo(address).bar()`

        contract_name = stmt_expr.func.value.func.id
        contract_address = Expr.parse_value_expr(stmt_expr.func.value.args[0], context)

    elif (
        isinstance(stmt_expr.func.value, vy_ast.Attribute)
        and stmt_expr.func.value.attr in context.globals
        and hasattr(context.globals[stmt_expr.func.value.attr].typ, "name")
    ):
        # e.g. `self.foo.bar()`

        contract_name = context.globals[stmt_expr.func.value.attr].typ.name
        type_ = stmt_expr.func.value._metadata["type"]
        var = context.globals[stmt_expr.func.value.attr]
        contract_address = unwrap_location(
            LLLnode.from_list(
                type_.position.position,
                typ=var.typ,
                location="storage",
                pos=getpos(stmt_expr),
                annotation="self." + stmt_expr.func.value.attr,
            )
        )

    return external_call(
        stmt_expr,
        context,
        contract_name,
        contract_address,
        value=value,
        gas=gas,
    )
