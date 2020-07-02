from vyper import ast as vy_ast
from vyper.exceptions import (
    StateAccessViolation,
    StructureException,
    TypeCheckFailure,
)
from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import getpos, pack_arguments, unwrap_location
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    TupleLike,
    get_size_of_type,
    get_static_size_of_type,
    has_dynamic_data,
)


def external_call(node, context, interface_name, contract_address, pos, value=None, gas=None):
    from vyper.parser.expr import Expr

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
                types_list = output_type.members
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


def get_external_call_output(sig, context):
    if not sig.output_type:
        return 0, 0, []
    output_placeholder = context.new_placeholder(typ=sig.output_type)
    output_size = get_size_of_type(sig.output_type) * 32
    if isinstance(sig.output_type, BaseType):
        returner = [0, output_placeholder]
    elif isinstance(sig.output_type, ByteArrayLike):
        returner = [0, output_placeholder + 32]
    elif isinstance(sig.output_type, TupleLike):
        returner = [0, output_placeholder]
    elif isinstance(sig.output_type, ListType):
        returner = [0, output_placeholder]
    else:
        raise TypeCheckFailure(f"Invalid output type: {sig.output_type}")
    return output_placeholder, output_size, returner


def get_external_interface_keywords(stmt_expr, context):
    from vyper.parser.expr import Expr

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
    from vyper.parser.expr import Expr

    value, gas = get_external_interface_keywords(stmt_expr, context)

    if isinstance(stmt_expr.func, vy_ast.Attribute) and isinstance(
        stmt_expr.func.value, vy_ast.Call
    ):
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
        and stmt_expr.func.value.attr in context.sigs
    ):  # noqa: E501
        contract_name = stmt_expr.func.value.attr
        var = context.globals[stmt_expr.func.value.attr]
        contract_address = unwrap_location(
            LLLnode.from_list(
                var.pos,
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

    elif (
        isinstance(stmt_expr.func.value, vy_ast.Attribute)
        and stmt_expr.func.value.attr in context.globals
        and hasattr(context.globals[stmt_expr.func.value.attr].typ, "name")
    ):

        contract_name = context.globals[stmt_expr.func.value.attr].typ.name
        var = context.globals[stmt_expr.func.value.attr]
        contract_address = unwrap_location(
            LLLnode.from_list(
                var.pos,
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
