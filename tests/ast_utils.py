from vyper.ast.nodes import VyperNode


def deepequals(node: VyperNode, other: VyperNode):
    # checks two nodes are recursively equal, ignoring metadata
    # like line info.
    if not isinstance(other, type(node)):
        return False

    if isinstance(node, list):
        if len(node) != len(other):
            return False
        return all(deepequals(a, b) for a, b in zip(node, other))

    if not isinstance(node, VyperNode):
        return node == other

    if getattr(node, "node_id", None) != getattr(other, "node_id", None):
        return False
    for field_name in (i for i in node.get_fields() if i not in VyperNode.__slots__):
        lhs = getattr(node, field_name, None)
        rhs = getattr(other, field_name, None)
        if not deepequals(lhs, rhs):
            return False
    return True
