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
    TypeMismatchException,
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


def compare_types(left, right, node):
    """
    Compares types.

    Types may be given as a single type object, a Constant ast node, or a sequence
    containing types and/or constants.

    Arguments
    ---------
    left : _BaseType | Constant | Sequence
        The left side of the comparison.
    right : _BaseType | Constant | Sequence
        The right side of the comparison.
    node
        The node where the comparison is taking place (for source highlights if
        an exception is raised).
    """
    if isinstance(right, (list, tuple)):
        if not hasattr(left, '__len__'):
            raise TypeMismatchException(
                f"Cannot perform array operation against base type: {left}", node
            )
        if len(left) != len(right):
            raise TypeMismatchException(
                f"Invalid length for operation, expected {len(left)} got {len(right)}", node
            )
        for i in range(len(right)):
            compare_types(left[i], right[i], node)
        return

    literals = [i for i in (left, right) if isinstance(i, vy_ast.Constant)]
    types = [i for i in (left, right) if i not in literals]

    if not types:
        if type(node.left) != type(node.right):  # NOQA: E721
            raise TypeMismatchException(
                "Cannot perform operation between "
                f"{node.left.ast_type} and {node.right.ast_type}",
                node
            )

    elif len(types) == 1:
        types[0].validate_literal(literals[0])

    else:
        if left != right:
            raise TypeMismatchException(
                f"Cannot perform operation between {left} and {right}", node
            )
