from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    operators,
)
from vyper.context.datatypes.bases import (
    IntegerType,
    UnionType,
)
from vyper.context.utils import (
    get_leftmost_id,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
)


def get_type_from_annotation(namespace, node):
    """
    Returns a type class for the given node.

    Arguments
    ---------
    node : VyperNode
        AST node from AnnAssign.annotation, outlining the type
        to be created.


    Returns
    -------
    _BaseType
        If the base_type member of this object has an _as_array member
        and the node argument includes a subscript, the return type will
        be ArrayType. Otherwise it will be base_type.
    """
    type_name = get_leftmost_id(node)
    type_obj = namespace[type_name]

    if getattr(type_obj, '_as_array', False) and isinstance(node, vy_ast.Subscript):
        length = _get_index_value(namespace, node.slice)
        return [type_obj.from_annotation(namespace, node.value)] * length
    else:
        return type_obj.from_annotation(namespace, node)


def _get_index_value(namespace, node):
    if not isinstance(node, vy_ast.Index):
        raise

    if isinstance(node.value, vy_ast.Int):
        return node.value.value

    if isinstance(node.value, vy_ast.Name):
        slice_name = node.value.id
        length = namespace[slice_name]

        if not length.is_constant:
            raise StructureException("Slice must be an integer or constant", node)

        typ = length.type
        if not isinstance(typ, IntegerType):
            raise StructureException(f"Invalid type for Slice: '{typ}'", node)
        if typ.unit:
            raise StructureException(f"Slice value must be unitless, not '{typ.unit}'", node)
        return length.literal_value

    raise StructureException("Slice must be an integer or constant", node)


def get_type_from_literal(namespace, node: vy_ast.Constant):
    base_types = [
        i for i in namespace.values() if
        hasattr(i, '_id') and hasattr(i, '_valid_literal')
    ]
    valid_types = UnionType()
    for typ in base_types:
        try:
            valid_types.add(typ.from_literal(namespace, node))
        # TODO catch specific exception, raise others (useful for e.g. address checksum fail)
        except Exception:
            continue
    if not valid_types:
        raise InvalidLiteralException(
            f"Could not determine type for literal value '{node.node_source_code}'",
            node
        )
    if len(valid_types) == 1:
        return valid_types.pop()
    return valid_types


def get_type_from_node(namespace, node):
    """
    Returns the type value of a node without any validation.

    # TODO if the node is a constant, it just returns the node, document this
    """
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_type_from_node(namespace, i) for i in node.elts)
    if isinstance(node, (vy_ast.List)):
        if not node.elts:
            return []
        values = [get_type_from_node(namespace, i) for i in node.elts]
        for i in values[1:]:
            compare_types(values[0], i, node)
        return values

    if isinstance(node, vy_ast.Constant):
        return get_type_from_literal(namespace, node)
    if isinstance(node, vy_ast.Name):
        return _get_name(namespace, node).type
    if isinstance(node, (vy_ast.Attribute)):
        return _get_attribute(namespace, node).type
    if isinstance(node, vy_ast.Subscript):
        var, idx = _get_subscript(namespace, node)
        return var.type[idx]
    if isinstance(node, (vy_ast.Op, vy_ast.Compare)):
        return operators.validate_operation(namespace, node)
    raise CompilerPanic(f"Cannot get type from object: {type(node).__name__}")


def get_value_from_node(namespace, node):
    """
    Returns the value of a node.

    Arguments
    ---------
    namespace : Namespace
        The active namespace that this value is being assigned within.

    Returns
    -------
        A literal value, Variable object, or sequence composed of one or both types.
    TODO finish docs
    """

    # TODO:
    # call - ...do the call...
    # attribute
    # folding

    if isinstance(node, vy_ast.List):
        # TODO validate that all types are like?
        return [get_value_from_node(namespace, node.elts[i]) for i in range(len(node.elts))]
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_value_from_node(namespace, node.elts[i]) for i in range(len(node.elts)))

    if isinstance(node, vy_ast.Constant):
        return node.value

    if isinstance(node, vy_ast.Name):
        return _get_name(namespace, node)

    if isinstance(node, vy_ast.Attribute):
        return _get_attribute(namespace, node)

    if isinstance(node, vy_ast.Subscript):
        base_var, idx = _get_subscript(namespace, node)
        return base_var.get_item(idx)
    # TODO folding
    # if isinstance(node, (vy_ast.BinOp, vy_ast.BoolOp, vy_ast.Compare)):
    #     return operators.validate_operation(namespace, node)
    raise


def _get_name(namespace, node, validation_type=None):
    var = namespace[node.id]
    # if not isinstance(var, Variable):
    #     raise VariableDeclarationException(f"{node.id} is not a variable", node)
    if var.enclosing_scope == "module" and not var.is_constant:
        raise StructureException("Cannot access storage variable directly, use self", node)
    if validation_type and var.type != validation_type:
        raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
    return var


def _get_attribute(namespace, node, validation_type=None):
    if node.value.id == "self":
        var = namespace[node.attr]
        if var.enclosing_scope != "module" or var.is_constant:
            raise StructureException(
                f"'{var.name}' is not a storage variable, do not use self to access it", node
            )
        if validation_type and var.type != validation_type:
            raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
        return var
    raise


def _get_subscript(namespace, node, validation_type=None):
    base_var = get_value_from_node(namespace, node.value)

    idx = get_value_from_node(namespace, node.slice.value)
    if idx >= len(base_var.type):
        raise StructureException("Array index out of range", node.slice)
    if idx < 0:
        raise StructureException("Array index cannot use negative integers", node.slice)
    return base_var, idx


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
    """

    if any(isinstance(i, (list, tuple)) for i in (left, right)):
        if not all(isinstance(i, (list, tuple)) for i in (left, right)):
            raise
        if len(left) != len(right):
            raise
        for lhs, rhs in zip(left, right):
            compare_types(lhs, rhs, node)
        return

    if not isinstance(left, set) and not isinstance(right, set):
        if not left.compare_type(right):
            raise TypeMismatchException(
                f"Cannot perform operation between {left} and {right}", node
            )

    left_check = isinstance(left, set) and not left.compare_type(right)
    right_check = isinstance(right, set) and not right.compare_type(left)

    if left_check or right_check:
        raise TypeMismatchException(
            f"Cannot perform operation between {left} and {right}", node
        )
