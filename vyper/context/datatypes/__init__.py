from vyper import ast as vy_ast

from vyper.context.utils import (
    get_leftmost_id,
)
from vyper.context.datatypes import (
    types as vy_types,
)
from vyper.exceptions import (
    StructureException,
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
        if not isinstance(typ, vy_types.IntegerType):
            raise StructureException(f"Invalid type for Slice: '{typ}'", node)
        if typ.unit:
            raise StructureException(f"Slice value must be unitless, not '{typ.unit}'", node)
        return length.literal_value

    raise StructureException("Slice must be an integer or constant", node)
