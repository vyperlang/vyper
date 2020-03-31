from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    definitions,
    namespace,
)
from vyper.context.types.union import (
    UnionType,
)
from vyper.context.utils import (
    compare_types,
    get_index_value,
)
from vyper.exceptions import (
    ConstancyViolation,
    InvalidLiteral,
    InvalidReference,
    InvalidType,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
    UnknownType,
    VyperException,
)


def get_definition_from_node(node: vy_ast.VyperNode):
    """
    Returns a definition object for the given node.

    If the given node is a `Constant`, or sequence containing `Constant`s, new
    Literal objects are created. If the given node is a `Variable` or type of
    expression, an attempt is made to evaluate it and return an existing value
    from the namespace.

    Arguments
    ---------
    node : VyperNode
        AST node representing a literal or already-defined object.

    Returns
    -------
    A literal value, definition object, or sequence composed of one or both types.
    """
    if isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        if not node.elts:
            raise InvalidLiteral(f"Cannot have empty {type(node)}", node)

        value = [get_definition_from_node(node.elts[i]) for i in range(len(node.elts))]
        if isinstance(node, vy_ast.List):
            for i in value[1:]:
                try:
                    compare_types(value[0].type, i.type, node)
                except TypeMismatch:
                    raise InvalidType("Array contains multiple types", node) from None

        if not next((i for i in value if isinstance(i, definitions.Reference)), False):
            return definitions.Literal.from_type(
                [i.type for i in value], "literal sequence", [i.value for i in value]
            )

        is_readonly = next(
            (False for i in value if not isinstance(i, definitions.ReadOnlyDefinition)), True
        )
        return definitions.Reference.from_type(
            [i.type for i in value], "sequence", is_readonly=is_readonly
        )

    if isinstance(node, vy_ast.Constant):
        type_ = _get_type_from_literal(node)
        return definitions.Literal.from_type(type_, "literal", node.value)

    if isinstance(node, vy_ast.Name):
        name = node.id
        if name not in namespace and name in namespace['self'].members:
            raise InvalidReference(
                f"'{name}' exists in the contract storage, access it as self.{name}", node
            )
        try:
            return namespace[node.id]
        except VyperException as exc:
            raise exc.with_annotation(node)

    if isinstance(node, vy_ast.Attribute):
        var = get_definition_from_node(node.value)
        return var.get_member(node)

    if isinstance(node, vy_ast.Subscript):
        base_type = get_definition_from_node(node.value)
        return base_type.get_index(node)

    if isinstance(node, vy_ast.Call):
        var = get_definition_from_node(node.func)
        value = var.fetch_call_return(node)
        if value is None:
            raise InvalidType(f"{var} did not return a value", node)
        return value

    if isinstance(node, (vy_ast.BinOp, vy_ast.BoolOp, vy_ast.UnaryOp, vy_ast.Compare)):
        return definitions.Reference.from_operation(node)

    raise StructureException(f"Cannot get definition from {type(node).__name__}", node)


def _get_type_from_literal(node: vy_ast.Constant):
    base_types = [
        i for i in namespace.values() if
        hasattr(i, '_id') and hasattr(i, '_valid_literal')
    ]
    valid_types = UnionType()
    for typ in base_types:
        try:
            valid_types.add(typ.from_literal(node))
        # TODO catch specific exception, raise others (useful for e.g. address checksum fail)
        except VyperException:
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
    """
    Wrapper around `get_definition_from_node`. Returns a literal value or raises.
    """
    value = get_definition_from_node(node)

    for i in (value if isinstance(value, (list, tuple)) else (value,)):
        if not isinstance(i, definitions.Literal):
            raise ConstancyViolation("Value must be a literal", node) from None

    if isinstance(value, definitions.Literal):
        return value
    return definitions.Literal.from_type(
        [i.type for i in value], "literal", [i.value for i in value]
    )


def get_type_from_annotation(node: vy_ast.VyperNode):
    """
    Returns a type object for the given annotation node.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node from the `.annotation` member of an `AnnAssign` node.

    Returns
    -------
    BaseType | list
        If the node defines an array, the return type will be a list
        of BaseType objects.
    """
    try:
        type_name = next(i.id for i in node.get_descendants(vy_ast.Name, include_self=True))
        type_obj = namespace[type_name]
    except (StopIteration, UndeclaredDefinition):
        raise UnknownType(f"Not a valid type", node) from None

    if getattr(type_obj, '_as_array', False) and isinstance(node, vy_ast.Subscript):
        try:
            length = get_index_value(node.slice)
        except VyperException as exc:
            raise UnknownType(str(exc)) from None
        return [get_type_from_annotation(node.value)] * length

    try:
        return type_obj.from_annotation(node)
    except AttributeError:
        raise UnknownType(f"'{type_name}' is not a valid type", node) from None
