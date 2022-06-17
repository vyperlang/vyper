# validation utils for ast
# TODO this really belongs in vyper/semantics/validation/utils
from typing import Optional, Union

from vyper.ast import nodes as vy_ast
from vyper.exceptions import ArgumentException, CompilerPanic, StructureException


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
        If arg_count[1] is -1, it is interpreted to mean that there is no
        limit to the number of arguments (ex. when the function has a
        variable number of arguments).
    kwargs : list, optional
        A list of valid keyword arguments. When arg_count is a tuple and the
        number of positional arguments exceeds the minimum, the excess values are
        considered to fill the first values on this list.

    Returns
    -------
        None. Raises an exception when the arguments are invalid.
    """

    if not isinstance(node, vy_ast.Call):
        raise StructureException("Expected Call", node)
    if not isinstance(arg_count, (int, tuple)):
        raise CompilerPanic(f"Invalid type for arg_count: {type(arg_count).__name__}")

    if isinstance(arg_count, tuple):
        if arg_count[1] == -1:
            # -1 is sentinel which means we have varargs.
            # set arg_count[1] to some large number that we
            # would never see in practice
            arg_count = (arg_count[0], 2 ** 64)

        if arg_count[0] == arg_count[1]:
            arg_count == arg_count[0]

    if isinstance(node.func, vy_ast.Attribute):
        msg = f" for call to '{node.func.attr}'"
    elif isinstance(node.func, vy_ast.Name):
        msg = f" for call to '{node.func.id}'"

    if isinstance(arg_count, int) and len(node.args) != arg_count:
        if not node.args:
            exc_node = node
        elif len(node.args) < arg_count:
            exc_node = node.args[-1]
        else:
            exc_node = node.args[arg_count]
        raise ArgumentException(
            f"Invalid argument count{msg}: expected {arg_count}, got {len(node.args)}", exc_node
        )

    if isinstance(arg_count, tuple) and not arg_count[0] <= len(node.args) <= arg_count[1]:
        if not node.args:
            exc_node = node
        elif len(node.args) < arg_count[0]:
            exc_node = node.args[-1]
        else:
            exc_node = node.args[arg_count[1]]
        raise ArgumentException(
            f"Invalid argument count{msg}: expected {arg_count[0]} "
            f"to {arg_count[1]}, got {len(node.args)}",
            exc_node,
        )

    if kwargs is None:
        if node.keywords:
            raise ArgumentException("Keyword arguments are not accepted here", node.keywords[0])
        return

    kwargs_seen = set()
    for key in node.keywords:
        if key.arg is None:
            raise StructureException("Use of **kwargs is not supported", key.value)
        if key.arg not in kwargs:
            raise ArgumentException(f"Invalid keyword argument '{key.arg}'", key)
        if key.arg in kwargs_seen:
            raise ArgumentException(f"Duplicate keyword argument '{key.arg}'", key)
        kwargs_seen.add(key.arg)


def validate_literal_nodes(vyper_module: vy_ast.Module) -> None:
    """
    Individually validate Vyper AST nodes.

    Calls the `validate` method of each node to verify that literal nodes
    do not contain invalid values.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top level Vyper AST node.
    """
    for node in vyper_module.get_descendants():
        if hasattr(node, "validate"):
            node.validate()
