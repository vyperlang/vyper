from typing import (
    Optional,
    Union,
)

from vyper.ast import (
    nodes as vy_ast,
)
from vyper.exceptions import (
    ArgumentException,
    CompilerPanic,
    StructureException,
)


def validate_call_args(
    node: vy_ast.Call, arg_count: Union[int, tuple], kwargs: Optional[list] = None
) -> None:
    """
    Validate positional and keyword arguments of a Call node.

    This function does not handle type checking of arguments, it only checks
    correctness of the number of arguments given and keyword names.

    Arguments
    ---------
    node : Call
        Vyper ast Call node to be validated.
    arg_count : int | tuple
        The required number of positional arguments. When given as a tuple the
        value is interpreted as the minimum and maximum number of arguments.
    kwargs : list, optional
        A list of valid keyword arguments. When arg_count is a tuple and the
        number of positional arguments exceeds the minimum, the excess values are
        considered to fill the first values on this list.

    Returns
    -------
        None. Raises an exception when the arguments are invalid.
    """
    if kwargs is None:
        kwargs = []
    if not isinstance(node, vy_ast.Call):
        raise StructureException("Expected Call", node)
    if not isinstance(arg_count, (int, tuple)):
        raise CompilerPanic(f"Invalid type for arg_count: {type(arg_count).__name__}")

    if isinstance(arg_count, int) and len(node.args) != arg_count:
        raise ArgumentException(
            f"Invalid argument count: expected {arg_count}, got {len(node.args)}", node
        )
    elif (
        isinstance(arg_count, tuple)
        and not arg_count[0] <= len(node.args) <= arg_count[1]
    ):
        raise ArgumentException(
            f"Invalid argument count: expected between "
            f"{arg_count[0]} and {arg_count[1]}, got {len(node.args)}",
            node,
        )

    if not kwargs and node.keywords:
        raise ArgumentException(
            "Keyword arguments are not accepted here", node.keywords[0]
        )
    for key in node.keywords:
        if key.arg is None:
            raise StructureException("Use of **kwargs is not supported", key.value)
        if key.arg not in kwargs:
            raise ArgumentException(f"Invalid keyword argument '{key.arg}'", key)
        if (
            isinstance(arg_count, tuple)
            and kwargs.index(key.arg) < len(node.args) - arg_count[0]
        ):
            raise ArgumentException(
                f"'{key.arg}' was given as a positional argument", key
            )
