from typing import Optional

from vyper import ast as vy_ast


def get_folded_value(node: vy_ast.VyperNode) -> Optional[vy_ast.VyperNode]:
    if isinstance(node, vy_ast.Constant):
        return node
    elif isinstance(node, vy_ast.Index):
        if isinstance(node.value, vy_ast.Constant):
            return node.value

    return node._metadata.get("folded_value")
