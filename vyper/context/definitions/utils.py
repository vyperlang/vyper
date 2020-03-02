from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.exceptions import (
    StructureException,
)


def get_value_from_node(node: vy_ast.VyperNode):
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
        return [get_value_from_node(node.elts[i]) for i in range(len(node.elts))]
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_value_from_node(node.elts[i]) for i in range(len(node.elts)))

    if isinstance(node, vy_ast.Constant):
        return node.value

    if isinstance(node, vy_ast.Name):
        name = node.id
        if name not in namespace and name in namespace['self'].members:
            raise StructureException(
                f"'{name}' is a storage variable, access it as self.{name}", node
            )
        return namespace[node.id]

    if isinstance(node, vy_ast.Attribute):
        var = get_value_from_node(node.value)
        return var.get_member(node)

    if isinstance(node, vy_ast.Subscript):
        base_type = get_value_from_node(node.value)
        return base_type.get_index(node)

    if isinstance(node, vy_ast.Call):
        var = get_value_from_node(node.func)
        return var.validate_call(node)

    # TODO folding

    raise StructureException(f"Unsupported node type for get_value: {node.ast_type}", node)
