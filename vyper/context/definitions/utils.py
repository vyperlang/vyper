from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    definitions,
    namespace,
)
from vyper.context.types import (
    bases,
    utils,
)
from vyper.exceptions import (
    ConstancyViolation,
    InvalidLiteral,
    InvalidOperation,
    InvalidReference,
    InvalidType,
    StructureException,
)


def get_definition_from_node(node: vy_ast.VyperNode):
    """
    Returns a definition object for the given node.

    Arguments
    ---------
    node : VyperNode
        AST node representing an already-defined object.

    Returns
    -------
    A literal value, definition object, or sequence composed of one or both types.
    """
    # TODO return a single item instead of a sequence
    if isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        # TODO validate that all types are like?
        value = [get_definition_from_node(node.elts[i]) for i in range(len(node.elts))]
        if next((i for i in value if isinstance(i, definitions.Variable)), None):
            return definitions.Variable("", [i.type for i in value])
        if next((i for i in value if isinstance(i, definitions.EnvironmentVariable)), None):
            return definitions.EnvironmentVariable("", [i.type for i in value])
        invalid = next((i for i in value if not isinstance(i, definitions.Literal)), None)
        if invalid:
            node = node.elts[value.index(invalid)]
            raise StructureException(f"Invalid type for sequence: {type(invalid).__name__}", node)
        return definitions.Literal([i.type for i in value], [i.value for i in value])

    if isinstance(node, vy_ast.Constant):
        type_ = _get_type_from_literal(node)
        return definitions.Literal(type_, node.value)

    if isinstance(node, vy_ast.Name):
        name = node.id
        if name not in namespace and name in namespace['self'].members:
            raise InvalidReference(
                f"'{name}' is a storage variable, access it as self.{name}", node
            )
        return namespace[node.id]

    if isinstance(node, vy_ast.Attribute):
        var = get_definition_from_node(node.value)
        return var.get_member(node)

    if isinstance(node, vy_ast.Subscript):
        base_type = get_definition_from_node(node.value)
        return base_type.get_index(node)

    if isinstance(node, vy_ast.Call):
        var = get_definition_from_node(node.func)
        return_type = var.get_call_return_type(node)
        # TODO functions should be able to indicate if the result is Var or Literal
        return definitions.Variable("", return_type)

    if isinstance(node, (vy_ast.Op, vy_ast.Compare)):
        return get_definition_from_operation(node)

    raise StructureException(f"Cannot get definition from {node.ast_type}", node)


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
        raise InvalidLiteral(
            f"Could not determine type for literal value '{node.value}'",
            node
        )
    if len(valid_types) == 1:
        return valid_types.pop()
    return valid_types


def get_literal_or_raise(node):
    value = get_definition_from_node(node)

    for i in (value if isinstance(value, (list, tuple)) else (value,)):
        if type(i) is not definitions.Literal:
            raise ConstancyViolation("Value must be a literal", node) from None

    if isinstance(value, definitions.Literal):
        return value
    return definitions.Literal([i.type for i in value], [i.value for i in value])


def get_index_value(node):
    """
    Returns the literal value for a Subscript index.

    Arguments
    ---------
    node : Index
        Vyper ast node from the `slice` member of a Subscript node. Must be an
        Index object (Vyper does not support Slice or ExtSlice).

    Returns
    -------
    Literal integer value.
    """
    try:
        var = get_literal_or_raise(node.value)
    except ConstancyViolation:
        raise InvalidType("Slice must be an integer or constant", node)

    if not getattr(var.type, 'is_integer', False):
        raise InvalidType(f"Invalid type for Slice: '{var.type}'", node)
    if getattr(var.type, 'unit', None):
        raise InvalidType(f"Slice value cannot have a unit", node)
    return var.value


def get_definition_from_operation(node: vy_ast.VyperNode):
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
    value = get_definition_from_node(node.operand)
    value.type.validate_numeric_op(node)
    return value


# x and y, x or y
def _get_boolean_op(node):
    values = [get_definition_from_node(i) for i in node.values]
    values[0].type.validate_boolean_op(node)
    for item in values[1:]:
        utils.compare_types(values[0].type, item.type, node)
    if next((i for i in values if isinstance(i, definitions.Variable)), None):
        return definitions.Variable("", values[0].type)
    return definitions.Literal(values[0].type, None)


def _get_binop(node):
    left, right = (get_definition_from_node(i) for i in (node.left, node.right))
    utils.compare_types(left.type, right.type, node)
    left.type.validate_numeric_op(node)
    type_ = left.type
    if isinstance(left.type, set) and len(left.type) == 1:
        type_ = next(iter(type_))
    if next((i for i in (left, right) if isinstance(i, definitions.Variable)), None):
        return definitions.Variable("", type_)
    return definitions.Literal(type_, None)


def _get_comparator(node):
    if len(node.ops) != 1:
        raise StructureException("Cannot perform comparison between more than two elements", node)
    left, right = (get_definition_from_node(i) for i in (node.left, node.comparators[0]))

    if isinstance(node.ops[0], vy_ast.In):
        if not getattr(left.type, 'is_value_type', None) or not isinstance(right.type, list):
            raise InvalidOperation(
                "Can only use 'in' comparator between single type and list", node
            )
        utils.compare_types(left.type, right[0].type, node)
    else:
        if isinstance(left.type, (list, tuple)):
            if not isinstance(node.ops[0], vy_ast.Eq, vy_ast.NotEq):
                raise InvalidOperation(
                    "Can only perform equality comparisons between sequence types", node
                )
        else:
            left.type.validate_comparator(node)
        utils.compare_types(left.type, right.type, node)

    if next((i for i in (left, right) if isinstance(i, definitions.Variable)), None):
        return definitions.Variable("", namespace['bool'])
    return definitions.Literal(namespace['bool'], None)
