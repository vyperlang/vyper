from typing import (
    Optional,
    Set,
)

from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
)


def check_call_args(node: vy_ast.VyperNode, argcount: int, kwargs: Optional[Set] = None) -> None:
    if not isinstance(node, vy_ast.Call):
        raise StructureException("Expected Call", node)
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


def get_leftmost_id(node: vy_ast.VyperNode) -> str:
    return next(i.id for i in node.get_all_children({'ast_type': 'Name'}, True))


def check_numeric_bounds(type_str: str, node: vy_ast.Num) -> bool:
    """Returns the lower and upper bound for an integer type."""
    size = int(type_str.strip("uint") or 256)
    if size < 8 or size > 256 or size % 8:
        raise ValueError(f"Invalid type: {type_str}")
    if type_str.startswith("u"):
        lower, upper = 0, 2 ** size - 1
    else:
        lower, upper = -(2 ** (size - 1)), 2 ** (size - 1) - 1

    value = node.value
    if value < lower:
        raise InvalidLiteralException(f"Value is below lower bound for given type ({lower})", node)
    if value > upper:
        raise InvalidLiteralException(f"Value exceeds upper bound for given type ({upper})", node)
