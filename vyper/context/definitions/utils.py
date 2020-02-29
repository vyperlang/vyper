from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    StructureException,
)


def get_value_from_node(namespace, node):
    """
    Returns the value of a node.

    Arguments
    ---------
    namespace : Namespace
        The namespace that this value exists within.

    Returns
    -------
        A literal value, definition object, or sequence composed of one or both types.
    TODO finish docs
    """

    if isinstance(node, vy_ast.List):
        # TODO validate that all types are like?
        return [get_value_from_node(namespace, node.elts[i]) for i in range(len(node.elts))]
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_value_from_node(namespace, node.elts[i]) for i in range(len(node.elts)))

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
        var = get_value_from_node(namespace, node.value)
        return var.get_member(node)

    if isinstance(node, vy_ast.Subscript):
        base_type = get_value_from_node(namespace, node.value)
        return base_type.get_index(node)

    if isinstance(node, vy_ast.Call):
        var = get_value_from_node(namespace, node.func)
        return var.validate_call(node)

    # TODO folding
    # if isinstance(node, (vy_ast.BinOp, vy_ast.BoolOp, vy_ast.Compare)):
    #     return operators.validate_operation(namespace, node)

    raise StructureException(f"Unsupported node type for get_value: {node.ast_type}", node)
