from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    typeutils,
    variables,
)
from vyper.exceptions import (
    StructureException,
)


def validate_operation(namespace, node):
    if isinstance(node, vy_ast.UnaryOp):
        return _validate_unary_op(namespace, node)
    if isinstance(node, vy_ast.BinOp):
        return _validate_numeric_op(namespace, node)
    elif isinstance(node, vy_ast.BoolOp):
        return _validate_boolean_op(namespace, node, node.values)
    elif isinstance(node, vy_ast.Compare):
        return _validate_comparator(namespace, node)


def _split_literal_and_assigned(namespace, node_list):
    node_list = [variables.get_type(namespace, i) for i in node_list]

    literals = [i for i in node_list if isinstance(i, vy_ast.Constant)]
    assigned = [i for i in node_list if i not in literals]
    return literals, assigned


def _validate_unary_op(namespace, node):
    node_type = variables.get_type(namespace, node.operand)
    if isinstance(node.operand, vy_ast.BinOp):
        return node_type
    node_type.validate_numeric_op(node)
    return node_type


# x and y, x or y
def _validate_boolean_op(namespace, node):
    literals, assigned = _split_literal_and_assigned(namespace, node.values)
    non_bool = next((i for i in literals if not isinstance(i, vy_ast.NameConstant)), False)
    if non_bool:
        raise StructureException(
            f"Invalid literal type for numeric operation: {non_bool.ast_type}", non_bool
        )
    if assigned:
        assigned[0].validate_boolean_op(node)
        for i in assigned[1:]:
            typeutils.compare_types(assigned[0], i, node)
        return assigned[0]
    return literals[0]


def _validate_numeric_op(namespace, node):
    node_list = [variables.get_type(namespace, i) for i in (node.left, node.right)]
    literals, assigned = _split_literal_and_assigned(namespace, (node.left, node.right))
    if not assigned:
        if not isinstance(node.left, (vy_ast.Int, vy_ast.Decimal)):
            raise StructureException(
                f"Invalid literal type for numeric operation: {node.left.ast_type}", node
            )
    else:
        assigned[0].validate_numeric_op(node)
    typeutils.compare_types(node_list[0], node_list[1], node)
    if assigned:
        return assigned[0]
    # TODO this is bad - need to fold!
    return node.left


def _validate_comparator(namespace, node):
    if len(node.ops) != 1:
        raise StructureException("Cannot have a comparison with more than two elements", node)
    left, right = [variables.get_type(namespace, i) for i in (node.left, node.comparators[0])]
    if isinstance(node.ops[0], vy_ast.In):
        pass
    else:
        left.validate_comparator(node)
        typeutils.compare_types(left, right, node)
    return left
