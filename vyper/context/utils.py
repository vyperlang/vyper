from typing import (
    Optional,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.types import (
    bases,
)
from vyper.exceptions import (
    CompilerPanic,
    StructureException,
)


class VyperNodeVisitorBase:

    ignored_types = ()
    scope_name = ""

    def visit(self, node):
        if isinstance(node, self.ignored_types):
            return
        visitor_fn = getattr(self, f'visit_{node.ast_type}', None)
        if visitor_fn is None:
            raise StructureException(
                f"Unsupported syntax for {self.scope_name} namespace: {node.ast_type}", node
            )
        visitor_fn(node)


def check_call_args(
    node: vy_ast.Call,
    arg_count: Union[int, tuple],
    kwargs: Optional[list] = None
) -> None:
    """
    Validates call arguments.

    Parameters
    ----------
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
        None if the arguments are valid. Raises if not.
    """
    if not isinstance(node, vy_ast.Call):
        raise StructureException("Expected Call", node)
    if not isinstance(arg_count, (int, tuple)):
        raise CompilerPanic(f"Invalid type for arg_count: {type(arg_count).__name__}")

    if isinstance(arg_count, int) and len(node.args) != arg_count:
        raise StructureException(
            f"Invalid argument count: expected {arg_count}, got {len(node.args)}", node
        )
    elif isinstance(arg_count, tuple) and not arg_count[0] <= len(node.args) <= arg_count[1]:
        raise StructureException(
            f"Invalid argument count: expected between "
            f"{arg_count[0]} and {arg_count[1]}, got {len(node.args)}",
            node
        )

    if kwargs is None and node.keywords:
        raise StructureException("Keyword arguments are not accepted here", node.keywords[0])
    for key in node.keywords:
        if key.arg is None:
            raise StructureException("Use of **kwargs is not supported", key.value)
        if key.arg not in kwargs:
            raise StructureException("Invalid keyword argument", key)
        if isinstance(arg_count, tuple) and kwargs.index(key.arg) < len(node.args)-arg_count[0]:
            raise StructureException(f"'{key.arg}' was already given as a positional argument", key)


def get_leftmost_id(node: vy_ast.VyperNode) -> str:
    return next(i.id for i in node.get_all_children({'ast_type': 'Name'}, True))


def get_index_value(namespace, node):
    if not isinstance(node, vy_ast.Index):
        raise

    if isinstance(node.value, vy_ast.Int):
        return node.value.value

    if isinstance(node.value, vy_ast.Name):
        slice_name = node.value.id
        length = namespace[slice_name]

        if not length.is_constant:
            raise StructureException("Slice must be an integer or constant", node)

        typ = length.type
        if not isinstance(typ, bases.IntegerType):
            raise StructureException(f"Invalid type for Slice: '{typ}'", node)
        if typ.unit:
            raise StructureException(f"Slice value must be unitless, not '{typ.unit}'", node)
        return length.literal_value()

    raise StructureException("Slice must be an integer or constant", node)
