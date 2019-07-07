from vyper import ast
from vyper.exceptions import (
    FunctionDeclarationException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    getpos,
    pack_arguments,
    unwrap_location,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    TupleLike,
    get_size_of_type,
)


def external_contract_call(node,
                           context,
                           contract_name,
                           contract_address,
                           pos,
                           value=None,
                           gas=None):
    from vyper.parser.expr import (
        Expr,
    )
    if value is None:
        value = 0
    if gas is None:
        gas = 'gas'
    if not contract_name:
        raise StructureException(
            f'Invalid external contract call "{node.func.attr}".',
            node
        )
    if contract_name not in context.sigs:
        raise VariableDeclarationException(
            f'Contract "{contract_name}" not declared yet',
            node
        )
    method_name = node.func.attr
    if method_name not in context.sigs[contract_name]:
        raise FunctionDeclarationException(
            (
                "Function not declared yet: %s (reminder: "
                "function must be declared in the correct contract)"
                " The available methods are: %s"
            ) % (method_name, ",".join(context.sigs[contract_name].keys())),
            node.func
        )
    sig = context.sigs[contract_name][method_name]
    inargs, inargsize, _ = pack_arguments(
        sig,
        [Expr(arg, context).lll_node for arg in node.args],
        context,
        pos=pos,
    )
    output_placeholder, output_size, returner = get_external_contract_call_output(sig, context)
    sub = [
        'seq',
        ['assert', ['extcodesize', contract_address]],
        ['assert', ['ne', 'address', contract_address]],
    ]
    if context.is_constant() or sig.const:
        sub.append([
            'assert',
            [
                'staticcall',
                gas, contract_address, inargs, inargsize, output_placeholder, output_size,
            ]
        ])
    else:
        sub.append([
            'assert',
            [
                'call',
                gas, contract_address, value, inargs, inargsize, output_placeholder, output_size,
            ]
        ])
    sub.extend(returner)
    o = LLLnode.from_list(sub, typ=sig.output_type, location='memory', pos=getpos(node))
    return o


def get_external_contract_call_output(sig, context):
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
    else:
        raise TypeMismatchException("Invalid output type: %s" % sig.output_type)
    return output_placeholder, output_size, returner


def get_external_contract_keywords(stmt_expr, context):
    from vyper.parser.expr import Expr
    value, gas = None, None
    for kw in stmt_expr.keywords:
        if kw.arg not in ('value', 'gas'):
            raise TypeMismatchException(
                'Invalid keyword argument, only "gas" and "value" supported.',
                stmt_expr,
            )
        elif kw.arg == 'gas':
            gas = Expr.parse_value_expr(kw.value, context)
        elif kw.arg == 'value':
            value = Expr.parse_value_expr(kw.value, context)
    return value, gas


def make_external_call(stmt_expr, context):
    from vyper.parser.expr import Expr
    value, gas = get_external_contract_keywords(stmt_expr, context)

    if isinstance(stmt_expr.func, ast.Attribute) and isinstance(stmt_expr.func.value, ast.Call):
        contract_name = stmt_expr.func.value.func.id
        contract_address = Expr.parse_value_expr(stmt_expr.func.value.args[0], context)

        return external_contract_call(
            stmt_expr,
            context,
            contract_name,
            contract_address,
            pos=getpos(stmt_expr),
            value=value,
            gas=gas,
        )

    elif isinstance(stmt_expr.func.value, ast.Attribute) and stmt_expr.func.value.attr in context.sigs:  # noqa: E501
        contract_name = stmt_expr.func.value.attr
        var = context.globals[stmt_expr.func.value.attr]
        contract_address = unwrap_location(LLLnode.from_list(
            var.pos,
            typ=var.typ,
            location='storage',
            pos=getpos(stmt_expr),
            annotation='self.' + stmt_expr.func.value.attr,
        ))

        return external_contract_call(
            stmt_expr,
            context,
            contract_name,
            contract_address,
            pos=getpos(stmt_expr),
            value=value,
            gas=gas,
        )

    elif isinstance(stmt_expr.func.value, ast.Attribute) and stmt_expr.func.value.attr in context.globals:  # noqa: E501
        contract_name = context.globals[stmt_expr.func.value.attr].typ.unit
        var = context.globals[stmt_expr.func.value.attr]
        contract_address = unwrap_location(LLLnode.from_list(
            var.pos,
            typ=var.typ,
            location='storage',
            pos=getpos(stmt_expr),
            annotation='self.' + stmt_expr.func.value.attr,
        ))

        return external_contract_call(
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
