from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    definitions,
    namespace,
)
from vyper.context.types import (
    bases,
)
from vyper.exceptions import (
    InvalidLiteral,
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
    if isinstance(node, vy_ast.List):
        # TODO validate that all types are like?
        return [get_definition_from_node(node.elts[i]) for i in range(len(node.elts))]
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_definition_from_node(node.elts[i]) for i in range(len(node.elts)))

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

    # TODO folding

    raise StructureException(f"Unsupported node type for get_value: {node.ast_type}", node)


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


def get_variable_or_raise(node):
    return _get_or_raise(node, definitions.Variable)


def get_literal_or_raise(node):
    value = _get_or_raise(node, definitions.Literal)
    if isinstance(value, definitions.Literal):
        return value
    return definitions.Literal([i.type for i in value], [i.value for i in value])


def _get_or_raise(node, type_):
    definition = get_definition_from_node(node)

    for i in (definition if isinstance(definition, (list, tuple)) else (definition,)):
        if not isinstance(i, type_):
            raise

    return definition


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
    except:
        raise InvalidType("Slice must be an integer or constant", node)

    if not getattr(var.type, 'is_integer', False):
        raise InvalidType(f"Invalid type for Slice: '{var.type}'", node)
    if getattr(var.type, 'unit', None):
        raise InvalidType(f"Slice value cannot have a unit", node)
    return var.value
