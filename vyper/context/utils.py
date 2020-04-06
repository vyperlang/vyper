from typing import (
    Optional,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.types.union import (
    UnionType,
)
from vyper.exceptions import (
    ArgumentException,
    ArrayIndexException,
    CompilerPanic,
    InvalidType,
    StructureException,
    TypeMismatch,
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


def validate_call_args(
    node: vy_ast.Call,
    arg_count: Union[int, tuple],
    kwargs: Optional[list] = None
) -> None:
    """
    Validates call arguments.

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
        None if the arguments are valid. Raises if not.
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
    elif isinstance(arg_count, tuple) and not arg_count[0] <= len(node.args) <= arg_count[1]:
        raise ArgumentException(
            f"Invalid argument count: expected between "
            f"{arg_count[0]} and {arg_count[1]}, got {len(node.args)}",
            node
        )

    if not kwargs and node.keywords:
        raise ArgumentException("Keyword arguments are not accepted here", node.keywords[0])
    for key in node.keywords:
        if key.arg is None:
            raise StructureException("Use of **kwargs is not supported", key.value)
        if key.arg not in kwargs:
            raise ArgumentException(f"Invalid keyword argument '{key.arg}'", key)
        if isinstance(arg_count, tuple) and kwargs.index(key.arg) < len(node.args)-arg_count[0]:
            raise ArgumentException(f"'{key.arg}' was given as a positional argument", key)


def compare_types(expected, given, node):
    """
    Compares types.

    Types may be given as a single type object, a Constant ast node, or a sequence
    containing types and/or constants.

    Arguments
    ---------
    expected : BaseType | Constant | Sequence
        The expected type for the comparison. For assignments, this is the type
        of the left hand side.
    right : BaseType | Constant | Sequence
        The given type for the comparison.
    node : VyperNode
        The node where the comparison is taking place (for source highlights if
        an exception is raised).

    Returns
    -------
    None. If the comparison fails an exception is raised.
    """
    if any(isinstance(i, (list, tuple)) for i in (expected, given)):
        if not all(isinstance(i, (list, tuple)) for i in (expected, given)):
            raise TypeMismatch(
                f"Cannot perform operation between single type and compound type", node
            )
        if len(expected) != len(given):
            raise TypeMismatch(
                f"Imbalanced operation: expected {len(expected)} values, got {len(given)}", node
            )
        for lhs, rhs in zip(expected, given):
            compare_types(lhs, rhs, node)
        return

    if not isinstance(expected, UnionType) and not isinstance(given, UnionType):
        if not expected._compare_type(given):
            raise TypeMismatch(f"Expected {expected}, got {given}", node)

    left_check = isinstance(expected, UnionType) and not expected._compare_type(given)
    right_check = isinstance(given, UnionType) and not given._compare_type(expected)

    if left_check or right_check:
        raise TypeMismatch(f"Expected {expected}, got {given}", node)


def is_subtype(instance, class_):

    if isinstance(instance, UnionType):
        return all(isinstance(i, class_) for i in instance)
    return isinstance(instance, class_)


def get_index_value(node: vy_ast.Index):
    """
    Returns the literal value for a Subscript index.

    Arguments
    ---------
    node : Index
        Vyper ast node from the `slice` member of a Subscript node. Must be an
        `Index` object (Vyper does not support `Slice` or `ExtSlice`).

    Returns
    -------
    Literal integer value.
    """

    if not isinstance(node.value, vy_ast.Int):
        raise InvalidType(f"Invalid type for Slice: '{type(node.value)}'", node)

    if node.value.value <= 0:
        raise ArrayIndexException("Slice must be greater than 0", node)

    return node.value.value
