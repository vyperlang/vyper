from typing import Optional

from vyper import ast as vy_ast


def get_folded_value(node: vy_ast.VyperNode) -> Optional[vy_ast.VyperNode]:
    if isinstance(node, vy_ast.Constant):
        return node

    return node._metadata.get("folded_value")
