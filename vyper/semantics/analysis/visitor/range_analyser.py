from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import InvalidLiteral, StateAccessViolation, StructureException, TypeMismatch
from vyper.semantics.analysis.utils import get_common_types, validate_expected_type
from vyper.semantics.types import IntegerT, VyperType


def analyse_range_call(node: vy_ast.Call) -> list[VyperType]:
    """
    Check that the arguments to a range() call are valid.
    :param node: call to range()
    :return: None
    """
    validate_call_args(node, (1, 2), kwargs=["bound"])
    kwargs = {s.arg: s.value for s in node.keywords or []}

    start, end = (vy_ast.Int(value=0), node.args[0]) if len(node.args) == 1 else node.args

    if "bound" in kwargs:
        return _analyse_range_bound(start, end, kwargs["bound"], node)
    if isinstance(start, vy_ast.Num):
        return _analyse_range_constant(start, end, node)
    return _analyse_range_sum(start, end, node)


def _analyse_range_constant(start: vy_ast.Num, end: vy_ast.VyperNode, node: vy_ast.Call) -> list[VyperType]:
    """
    Check that the arguments to a range(N, M) call are valid.
    :param start: first argument to range()
    :param end: second argument to range()
    :param node: range() call node
    :return: The common types of the arguments
    """
    if not isinstance(end, vy_ast.Num):
        raise StateAccessViolation("Value must be a literal integer", end)
    if end.value <= start.value:
        raise StructureException("End must be greater than start", end)
    return _get_common_argument_types(node)


def _analyse_range_bound(
        start: vy_ast.VyperNode,
        end: vy_ast.VyperNode,
        bound: vy_ast.VyperNode,
        node: vy_ast.Call
) -> list[VyperType]:
    """
    Check that the arguments to a range(x, bound=N) or range(x, y, bound=N) call are valid.
    :param start: first argument to range()
    :param end: second argument to range()
    :param bound: bound keyword argument to range()
    :param node: range() call node
    """
    if not isinstance(bound, vy_ast.Num):
        raise StateAccessViolation("Bound must be a literal", bound)
    if bound.value <= 0:
        raise StructureException("Bound must be at least 1", bound)
    if isinstance(start, vy_ast.Num) and isinstance(end, vy_ast.Num) and end.value - start.value > bound.value:
        raise StructureException(
            f"For loop has invalid number of iterations ({end.value - start.value}),"
            " the value must be between zero and the bound",
            node,
        )
    return _get_common_argument_types(node)


def _analyse_range_sum(start: vy_ast.VyperNode, end: vy_ast.VyperNode, node: vy_ast.Call) -> list[VyperType]:
    """
    Check that the arguments to a range(x, x + N) call are valid.
    :param start: first argument to range()
    :param end: second argument to range()
    :param node: range() call node
    :return: The common types of the arguments
    """
    if not isinstance(end, vy_ast.BinOp) or not isinstance(end.op, vy_ast.Add):
        raise StructureException(
            "Second element must be the first element plus a literal value", end
        )
    if not vy_ast.compare_nodes(start, end.left):
        raise StructureException(
            "First and second variable must be the same", end.left
        )
    if not isinstance(end.right, vy_ast.Int):
        raise InvalidLiteral("Literal must be an integer", end.right)
    if end.right.value < 1:
        raise StructureException(
            f"For loop has invalid number of iterations ({end.right.value}),"
            " the value must be greater than zero",
            end.right,
        )
    return _get_common_argument_types(node)


def _get_common_argument_types(node: vy_ast.Call) -> list[VyperType]:
    """
    Gets the common types of all arguments to a function call.
    :param node: range() call node
    :return: list of common types between all arguments
    """
    all_args = [*node.args, *[arg.value for arg in node.keywords]]
    for arg in all_args:
        validate_expected_type(arg, IntegerT.any())
    type_list = get_common_types(*all_args)
    if not type_list:
        raise TypeMismatch("Iterator values are of different types", node)
    return type_list
