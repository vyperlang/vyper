from vyper.ast import nodes as vy_ast


def fold(vyper_module: vy_ast.Module) -> None:
    """
    Perform literal folding operations on a Vyper AST.

    Arguments
    ---------
    vyper_module : Module
        Top-level Vyper AST node.
    """
    changed_nodes = 1
    while changed_nodes:
        changed_nodes = 0
        changed_nodes += replace_foldable_values(vyper_module)


def replace_foldable_values(vyper_module: vy_ast.Module) -> int:
    changed_nodes = 0

    for node in vyper_module.get_descendants():
        new_node = node._metadata.get("folded_value")
        if not isinstance(new_node, vy_ast.VyperNode):
            continue

        typ = node._metadata.get("type")
        # type annotations are not annotated e.g. String[2 ** 5]
        if typ:
            new_node._metadata["type"] = typ

        changed_nodes += 1
        vyper_module.replace_in_tree(node, new_node)

    return changed_nodes
