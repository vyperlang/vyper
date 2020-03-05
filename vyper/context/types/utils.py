from typing import (
    List,
    Tuple,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions.utils import (
    get_value_from_node,
)
from vyper.context.types import (
    bases,
)
from vyper.context.utils import (
    get_index_value,
)
from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
)


def compare_types(left, right, node):
    """
    Compares types.

    Types may be given as a single type object, a Constant ast node, or a sequence
    containing types and/or constants.

    Arguments
    ---------
    left : _BaseType | Constant | Sequence
        The left side of the comparison.
    right : _BaseType | Constant | Sequence
        The right side of the comparison.
    node
        The node where the comparison is taking place (for source highlights if
        an exception is raised).

    Returns
    -------
    None. If the comparison fails an exception is raised.
    """
    if hasattr(left, '_no_value'):
        raise StructureException(f"{left} is not an assignable type", node)

    if any(isinstance(i, (list, tuple)) for i in (left, right)):
        if not all(isinstance(i, (list, tuple)) for i in (left, right)):
            raise TypeMismatchException(
                f"Cannot perform operation between single type and compound type", node
            )
        if len(left) != len(right):
            raise StructureException(
                f"Imbalanced operation: {len(left)} left side values, {len(right)} right side", node
            )
        for lhs, rhs in zip(left, right):
            compare_types(lhs, rhs, node)
        return

    if not isinstance(left, set) and not isinstance(right, set):
        if not left._compare_type(right):
            raise TypeMismatchException(
                f"Cannot perform operation between {left} and {right}", node
            )

    left_check = isinstance(left, set) and not left._compare_type(right)
    right_check = isinstance(right, set) and not right._compare_type(left)

    if left_check or right_check:
        raise TypeMismatchException(
            f"Cannot perform operation between {left} and {right}", node
        )


def get_builtin_type(type_definition: Union[str, Tuple, List]):
    """
    Given a type definition, returns a type or list of types.

    Arguments
    ---------
    type_definition : str | tuple | list
        str - The name of a single type to be returned.
        tuple - The first value is the type name, the remaining values are passed
                as arguments when initializing the type class.
        list - Each item should be a string or tuple defining a single type.
    """
    if isinstance(type_definition, list):
        return [get_builtin_type(i) for i in type_definition]
    if isinstance(type_definition, set):
        return bases.UnionType(get_builtin_type(i) for i in type_definition)
    if isinstance(type_definition, tuple):
        return type(namespace[type_definition[0]])(*type_definition[1:])
    return type(namespace[type_definition])()


def get_type_from_annotation(node: vy_ast.VyperNode):
    """
    Returns a type object for the given annotation node.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node from the .annotation member of an AnnAssign node.

    Returns
    -------
    _BaseType | list
        If the node defines an array, the return type will be a list
        of _BaseType objects.
    """
    type_name = next(i.id for i in node.get_all_children({'ast_type': 'Name'}, True))
    type_obj = namespace[type_name]

    if getattr(type_obj, '_as_array', False) and isinstance(node, vy_ast.Subscript):
        length = get_index_value(node.slice)
        return [type_obj.from_annotation(node.value)] * length
    else:
        return type_obj.from_annotation(node)


def get_type_from_node(node: vy_ast.VyperNode):
    """
    Returns a type object for the given value node.

    Arguments
    ---------
    node : VyperNode
        AST node representing a literal or already-defined object.

    Returns
    -------
    _BaseType | list
        If the node represents an array, the return type will be a list
        of _BaseType objects.
    """
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_type_from_node(i) for i in node.elts)
    if isinstance(node, (vy_ast.List)):
        if not node.elts:
            return []
        values = [get_type_from_node(i) for i in node.elts]
        for i in values[1:]:
            compare_types(values[0], i, node)
        return values

    try:
        if isinstance(node, vy_ast.Constant):
            return _get_type_from_literal(node)

        if isinstance(node, (vy_ast.Op, vy_ast.Compare)):
            return get_type_from_operation(node)

        if isinstance(node, vy_ast.Call):
            var = get_value_from_node(node.func)
            return var.get_call_return_type(node)
    except AttributeError:
        raise StructureException(f"Invalid action for type: {node.ast_type}", node)

    var = get_value_from_node(node)
    if var is None:
        raise StructureException(f"{node.ast_type} did not return a value", node)
    return var.type


def _get_type_from_literal(node: vy_ast.Constant):
    base_types = [
        i for i in namespace.values() if
        hasattr(i, '_id') and hasattr(i, '_valid_literal')
    ]
    valid_types = bases.UnionType()
    for typ in base_types:
        try:
            valid_types.add(typ.from_literal(node))
        # TODO catch specific exception, raise others (useful for e.g. address checksum fail)
        except Exception:
            continue
    if not valid_types:
        raise InvalidLiteralException(
            f"Could not determine type for literal value '{node.value}'",
            node
        )
    if len(valid_types) == 1:
        return valid_types.pop()
    return valid_types


def get_type_from_operation(node: vy_ast.VyperNode):
    """
    Validates an operation or comparison and returns a type object.

    Arguments
    ---------
    node : UnaryOp, BinOp, BoolOp, Compare
        Vyper ast node.

    Returns
    -------
    _BaseType
        Vyper type object representing the outcome of the operation.
    """
    if isinstance(node, vy_ast.UnaryOp):
        return _get_unary_op(node)
    if isinstance(node, vy_ast.BinOp):
        return _get_binop(node)
    elif isinstance(node, vy_ast.BoolOp):
        return _get_boolean_op(node)
    elif isinstance(node, vy_ast.Compare):
        return _get_comparator(node)


def _get_unary_op(node):
    node_type = get_type_from_node(node.operand)
    node_type.validate_numeric_op(node)
    return node_type


# x and y, x or y
def _get_boolean_op(node):
    node_types = (get_type_from_node(i) for i in node.values)
    node_types[0].validate_boolean_op(node)
    for typ in node_types[1:]:
        compare_types(node_types[0], typ, node)
    return node_types[0]


def _get_binop(node):
    left, right = (get_type_from_node(i) for i in (node.left, node.right))
    compare_types(left, right, node)
    left.validate_numeric_op(node)
    if isinstance(left, set) and len(left) == 1:
        return next(iter(left))
    return left


def _get_comparator(node):
    if len(node.ops) != 1:
        raise StructureException("Cannot have a comparison with more than two elements", node)
    left, right = (get_type_from_node(i) for i in (node.left, node.comparators[0]))

    if isinstance(node.ops[0], vy_ast.In):
        if not isinstance(left, bases.ValueType) or not isinstance(right, list):
            raise StructureException(
                "Can only use 'in' comparator between single type and list", node
            )
        compare_types(left, right[0], node)
    else:
        if isinstance(left, (list, tuple)):
            if not isinstance(node.ops[0], vy_ast.Eq, vy_ast.NotEq):
                raise StructureException("Can only compare equality between sequences", node)
        else:
            left.validate_comparator(node)
        compare_types(left, right, node)

    if isinstance(left, set) and len(left) == 1:
        return next(iter(left))
    return left


def check_numeric_bounds(type_str: str, node: vy_ast.Num) -> bool:
    """
    Validates that a Num node's value is within the bounds of a given type.

    Arguments
    ---------
    type_str : str
        String representation of the type, e.g. "int128"
    node : Num
        Vyper ast node to validate

    Returns
    -------
    None. Raises an exception if the check fails.
    """
    size = int(type_str.strip("uint") or 256)
    if size < 8 or size > 256 or size % 8:
        raise ValueError(f"Invalid type: {type_str}")
    if type_str.startswith("u"):
        lower, upper = 0, 2 ** size - 1
    else:
        lower, upper = -(2 ** (size - 1)), 2 ** (size - 1) - 1

    value = node.value
    if value < lower:
        raise InvalidLiteralException(f"Value is below lower bound for given type ({lower})", node)
    if value > upper:
        raise InvalidLiteralException(f"Value exceeds upper bound for given type ({upper})", node)
