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

@type_check_wrapper
def pack_arguments(signature, args, context, stmt_expr, is_external_call):
    # NOTE cyclic dep
    from vyper.old_codegen.abi import abi_encode, abi_type_of

    pos = getpos(stmt_expr)

    # abi encoding just treats all args as a big tuple
    args_tuple_t = TupleType([x.typ for x in args])
    args_as_tuple = LLLnode.from_list(["multi"] + [x for x in args], typ=args_tuple_t)
    args_abi_t = abi_type_of(args_tuple_t)

    maxlen = args_abi_t.dynamic_size_bound() + args_abi_t.static_size()
    if is_external_call:
        maxlen += 32  # padding for the method id

    buf_t = ByteArrayType(maxlen=maxlen)
    buf = context.new_internal_variable(buf_t)

    mstore_method_id = []
    if is_external_call:
        # layout:
        # 32 bytes                 | args
        # 0x..00<method_id_4bytes> | args
        # the reason for the left padding is just so the alignment is easier.
        # if we were only targeting constantinople, we could align
        # to buf (and also keep code size small) by using
        # (mstore buf (shl signature.method_id 224))
        mstore_method_id.append(["mstore", buf, signature.method_id])
        buf += 32

    if len(signature.args) != len(args):
        return

    encode_args = abi_encode(buf, args_as_tuple, pos)

    if is_external_call:
        returner = [[buf - 4]]
        inargsize = buf_t.maxlen - 28
    else:
        return

    return (
        LLLnode.from_list(
            ["seq"] + mstore_method_id + [encode_args] + returner, typ=buf_t, location="memory"
        ),
        inargsize,
        buf,
    )


def external_call(node, context, interface_name, contract_address, pos, value=None, gas=None):
    from vyper.old_codegen.expr import Expr

    if value is None:
        value = 0
    if gas is None:
        gas = "gas"

    method_name = node.func.attr
    sig = context.sigs[interface_name][method_name]
    inargs, inargsize, _ = pack_arguments(
        sig,
        [Expr(arg, context).lll_node for arg in node.args],
        context,
        node.func,
        is_external_call=True,
    )
    output_placeholder, output_size, returner = get_external_call_output(sig, context)
    sub = ["seq"]
    if not output_size:
        # if we do not expect return data, check that a contract exists at the target address
        # we can omit this when we _do_ expect return data because we later check `returndatasize`
        sub.append(["assert", ["extcodesize", contract_address]])
    if context.is_constant() and sig.mutability not in ("view", "pure"):
        # TODO this can probably go
        raise StateAccessViolation(
            f"May not call state modifying function '{method_name}' "
            f"within {context.pp_constancy()}.",
            node,
        )

    if context.is_constant() or sig.mutability in ("view", "pure"):
        sub.append(
            [
                "assert",
                [
                    "staticcall",
                    gas,
                    contract_address,
                    inargs,
                    inargsize,
                    output_placeholder,
                    output_size,
                ],
            ]
        )
    else:
        sub.append(
            [
                "assert",
                [
                    "call",
                    gas,
                    contract_address,
                    value,
                    inargs,
                    inargsize,
                    output_placeholder,
                    output_size,
                ],
            ]
        )
    if output_size:
        # when return data is expected, revert when the length of `returndatasize` is insufficient
        output_type = sig.output_type
        if not has_dynamic_data(output_type):
            static_output_size = get_static_size_of_type(output_type) * 32
            sub.append(["assert", ["gt", "returndatasize", static_output_size - 1]])
        else:
            if isinstance(output_type, ByteArrayLike):
                types_list = (output_type,)
            elif isinstance(output_type, TupleLike):
                types_list = output_type.tuple_members()
            else:
                raise

            dynamic_checks = []
            static_offset = output_placeholder
            static_output_size = 0
            for typ in types_list:
                # ensure length of bytes does not exceed max allowable length for type
                if isinstance(typ, ByteArrayLike):
                    static_output_size += 32
                    # do not perform this check on calls to a JSON interface - we don't know
                    # for certain how long the expected data is
                    if not sig.is_from_json:
                        dynamic_checks.append(
                            [
                                "assert",
                                [
                                    "lt",
                                    [
                                        "mload",
                                        ["add", ["mload", static_offset], output_placeholder],
                                    ],
                                    typ.maxlen + 1,
                                ],
                            ]
                        )
                static_offset += get_static_size_of_type(typ) * 32
                static_output_size += get_static_size_of_type(typ) * 32

            sub.append(["assert", ["gt", "returndatasize", static_output_size - 1]])
            sub.extend(dynamic_checks)

    sub.extend(returner)

    return LLLnode.from_list(sub, typ=sig.output_type, location="memory", pos=getpos(node))


def get_external_interface_keywords(stmt_expr, context):
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
    # circular import!
    from vyper.old_codegen.expr import Expr

    value, gas = get_external_interface_keywords(stmt_expr, context)

    if isinstance(stmt_expr.func, vy_ast.Attribute) and isinstance(
        stmt_expr.func.value, vy_ast.Call
    ):
        # e.g. `Foo(address).bar()`

        contract_name = stmt_expr.func.value.func.id
        contract_address = Expr.parse_value_expr(stmt_expr.func.value.args[0], context)

        return external_call(
            stmt_expr,
            context,
            contract_name,
            contract_address,
            pos=getpos(stmt_expr),
            value=value,
            gas=gas,
        )

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
            pos=getpos(stmt_expr),
            value=value,
            gas=gas,
        )

    else:
        raise StructureException("Unsupported operator.", stmt_expr)
