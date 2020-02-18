from typing import (
    Optional,
    Set,
)

from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    StructureException,
)


def check_global_scope(node: vy_ast.VyperNode, description: str) -> None:
    if node.enclosing_scope != "global":
        raise StructureException(f"Cannot declare {description} outside of global namespace", node)


def check_call_args(node: vy_ast.VyperNode, argcount: int, kwargs: Optional[Set] = None) -> None:
    if not isinstance(node, vy_ast.Call):
        raise
    if len(node.args) != argcount:
        raise StructureException(
            f"Invalid argument count: expected {argcount}, got {len(node.args)}", node
        )
    if kwargs is None and node.keywords:
        raise StructureException("Keyword arguments are not accepted here", node.keywords[0])
    for key in node.keywords:
        if key.arg is None:
            raise StructureException("Use of **kwargs is not supported", key.value)
        if key.arg not in kwargs:
            raise


def get_leftmost_id(node: vy_ast.AnnAssign) -> str:
    return next(i.id for i in node.get_all_children({'ast_type': 'Name'}, True))
