import itertools
from typing import Callable, List

from vyper import ast as vy_ast
from vyper.context import types
from vyper.context.namespace import get_namespace
from vyper.context.types.bases import BaseTypeDefinition
from vyper.context.types.indexable.sequence import (
    ArrayDefinition,
    TupleDefinition,
)
from vyper.context.types.value.boolean import BoolDefinition
from vyper.exceptions import (
    ArrayIndexException,
    InvalidLiteral,
    InvalidOperation,
    InvalidReference,
    InvalidType,
    OverflowException,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
    UnknownAttribute,
    VyperException,
    ZeroDivisionException,
)


def _validate_op(node, types_list, validation_fn_name):
    if not types_list:
        raise TypeMismatch(f"Cannot perform {node.op.description} between dislike types", node)

    if len(types_list) == 1:
        getattr(types_list[0], validation_fn_name)(node)
        return types_list

    for type_ in types_list.copy():
        try:
            getattr(type_, validation_fn_name)(node)
        except InvalidOperation:
            types_list.remove(type_)

    if types_list:
        return types_list
    raise InvalidOperation(f"Cannot perform {node.op.description} on value", node)


class _ExprTypeChecker:
    """
    Node type-checker class.

    Type-check logic is implemented in `type_from_<NODE_CLASS>` methods, organized
    according to the Vyper ast node class. Calls to `get_exact_type_from_node` and
    `get_possible_types_from_node` are forwarded to this class, where the node
    class's method resolution order is examined to decide which method to call.
    """

    def __init__(self):
        self.namespace = get_namespace()

    def get_exact_type_from_node(self, node, only_definitions=True):
        """
        Find exactly one type for a given node.

        Raises StructureException if a single type cannot be determined.

        Arguments
        ---------
        node : VyperNode
            The vyper AST node to find a type for.
        only_definitions: bool, optional
            If True, raises when the return value is not a type definition
            e.g a primitive, meta type, or function call

        Returns
        -------
        Type object
        """
        types_list = self.get_possible_types_from_node(node, only_definitions)

        if len(types_list) > 1:
            raise StructureException("Ambiguous type", node)
        return types_list[0]

    def get_possible_types_from_node(self, node, only_definitions=True):
        """
        Find all possible types for a given node.

        Arguments
        ---------
        node : VyperNode
            The vyper AST node to find a type for.
        only_definitions: bool, optional
            If True, raises when the return value is not a type definition
            e.g a primitive, meta type, or function call

        Returns
        -------
        List
            A list of type objects
        """
        fn = self._find_fn(node)
        types_list = fn(node)
        if only_definitions:
            invalid = next((i for i in types_list if not isinstance(i, BaseTypeDefinition)), None)
            if invalid:
                if isinstance(invalid, type) and types.BasePrimitive in invalid.mro():
                    raise InvalidReference(
                        f"'{invalid._id}' is a type - expected a literal or variable", node
                    )
                else:
                    raise InvalidReference("Expected a literal or variable", node)
        return types_list

    def _find_fn(self, node):
        # look for a type-check method for each class in the given class mro
        for name in [i.__name__ for i in type(node).mro()]:
            if name == "VyperNode":
                break
            fn = getattr(self, f"types_from_{name}", None)
            if fn is not None:
                return fn

        raise StructureException("Cannot determine type of this object", node)

    def types_from_Attribute(self, node):
        # variable attribute, e.g. `foo.bar`
        var = self.get_exact_type_from_node(node.value)
        name = node.attr
        try:
            return [var.get_member(name, node)]
        except UnknownAttribute:
            if node.get("value.id") != "self":
                raise
            if name in self.namespace:
                raise InvalidReference(
                    f"'{name}' is not a storage variable, it should not be prepended with self",
                    node,
                ) from None
            raise UndeclaredDefinition(
                f"Storage variable '{name}' has not been declared", node
            ) from None

    def types_from_BinOp(self, node):
        # binary operation: `x + y`
        types_list = get_common_types(node.left, node.right)

        if (
            isinstance(node.op, (vy_ast.Div, vy_ast.Mod))
            and isinstance(node.right, vy_ast.Num)
            and not node.right.value
        ):
            raise ZeroDivisionException(f"{node.op.description} by zero", node)

        return _validate_op(node, types_list, "validate_numeric_op")

    def types_from_BoolOp(self, node):
        # boolean operation: `x and y`
        types_list = get_common_types(*node.values)
        _validate_op(node, types_list, "validate_boolean_op")
        return [BoolDefinition()]

    def types_from_Compare(self, node):
        # comparison: `x < y`
        if isinstance(node.op, vy_ast.In):
            # x in y
            left = self.get_possible_types_from_node(node.left)
            right = self.get_possible_types_from_node(node.right)
            if next((i for i in left if isinstance(i, ArrayDefinition)), False):
                raise InvalidOperation(
                    "Left operand in membership comparison cannot be Array type", node.left,
                )
            if next((i for i in right if not isinstance(i, ArrayDefinition)), False):
                raise InvalidOperation(
                    "Right operand must be Array for membership comparison", node.right
                )
            types_list = [i for i in left if _is_type_in_list(i, [i.value_type for i in right])]
            if not types_list:
                raise TypeMismatch(
                    "Cannot perform membership comparison between dislike types", node
                )
        else:
            types_list = get_common_types(node.left, node.right)
            _validate_op(node, types_list, "validate_comparator")
        return [BoolDefinition()]

    def types_from_Call(self, node):
        # function calls, e.g. `foo()`
        var = self.get_exact_type_from_node(node.func, False)
        return_value = var.fetch_call_return(node)
        if return_value:
            return [return_value]
        raise InvalidType(f"{var} did not return a value", node)

    def types_from_Constant(self, node):
        # literal value (integer, string, etc)
        types_list = []
        for primitive in types.get_primitive_types().values():
            try:
                obj = primitive.from_literal(node)
                types_list.append(obj)
            except VyperException:
                continue
        if types_list:
            return types_list

        if isinstance(node, vy_ast.Num):
            raise OverflowException(
                "Numeric literal is outside of allowable range for number types", node,
            )
        raise InvalidLiteral(f"Could not determine type for literal value '{node.value}'", node)

    def types_from_List(self, node):
        # literal array
        if not node.elements:
            raise InvalidLiteral("Cannot have an empty array", node)

        types_list = get_common_types(*node.elements)
        if types_list:
            return [ArrayDefinition(i, len(node.elements)) for i in types_list]

        raise InvalidLiteral("Array contains multiple, incompatible types", node)

    def types_from_Name(self, node):
        # variable name, e.g. `foo`
        name = node.id
        if name not in self.namespace and name in self.namespace["self"].members:
            raise InvalidReference(
                f"'{name}' is a storage variable, access it as self.{name}", node,
            )
        try:
            return [self.namespace[node.id]]
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def types_from_Subscript(self, node):
        # index access, e.g. `foo[1]`
        base_type = self.get_exact_type_from_node(node.value)
        return [base_type.get_index_type(node.slice.value)]

    def types_from_Tuple(self, node):
        types_list = [self.get_exact_type_from_node(i) for i in node.elements]
        # for item, type_ in zip(node.elements, types_list):
        #     if not isinstnace(BaseTypeDefinition
        return [TupleDefinition(types_list)]

    def types_from_UnaryOp(self, node):
        # unary operation: `-foo`
        types_list = self.get_possible_types_from_node(node.operand)
        return _validate_op(node, types_list, "validate_numeric_op")


def _is_type_in_list(obj, types_list):
    # check if a type object is in a list of types
    return next((True for i in types_list if i.compare_type(obj)), False)


def _filter(type_, fn_name, node):
    # filter function used when evaluating boolean ops and comparators
    try:
        getattr(type_, fn_name)(node)
        return True
    except InvalidOperation:
        return False


def get_possible_types_from_node(node):
    """
    Return a list of possible types for the given node.

    Raises if no possible types can be found.

    Arguments
    ---------
    node : VyperNode
        A vyper ast node.

    Returns
    -------
    List
        List of one or more BaseType objects.
    """
    return _ExprTypeChecker().get_possible_types_from_node(node, False)


def get_exact_type_from_node(node):
    """
    Return exactly one type for a given node.

    Raises if there is more than one possible type.

    Arguments
    ---------
    node : VyperNode
        A vyper ast node.

    Returns
    -------
    BaseType
        Type object.
    """

    return _ExprTypeChecker().get_exact_type_from_node(node, False)


def get_common_types(*nodes: vy_ast.VyperNode, filter_fn: Callable = None) -> List:
    """
    Return a list of common possible types between one or more nodes.

    Arguments
    ---------
    *nodes : VyperNode
        Vyper ast nodes.
    filter_fn : Callable, optional
        If given, results are filtered by this function prior to returning.

    Returns
    -------
    list
        List of zero or more `BaseType` objects.
    """
    common_types = _ExprTypeChecker().get_possible_types_from_node(nodes[0])

    for item in nodes[1:]:
        new_types = _ExprTypeChecker().get_possible_types_from_node(item)

        common = [i for i in common_types if _is_type_in_list(i, new_types)]
        rejected = [i for i in common_types if i not in common]
        common += [i for i in new_types if _is_type_in_list(i, rejected)]

        common_types = common

    if filter_fn is not None:
        common_types = [i for i in common_types if filter_fn(i)]

    return common_types


def _validate_literal_array(node, expected):
    # validate that every item within an array has the same type
    if len(node.elements) != expected.length:
        return False

    for item in node.elements:
        try:
            validate_expected_type(item, expected.value_type)
        except (InvalidType, TypeMismatch):
            return False

    return True


def validate_expected_type(node, expected_type):
    """
    Validate that the given node matches the expected type(s)

    Raises if the node does not match one of the expected types.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node.
    expected_type : Tuple | BaseType
        A type object, or tuple of type objects

    Returns
    -------
    None
    """
    given_types = _ExprTypeChecker().get_possible_types_from_node(node)
    if not isinstance(expected_type, tuple):
        expected_type = (expected_type,)

    if isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        # special case - for literal arrays or tuples we individually validate each item
        for expected in (i for i in expected_type if isinstance(i, ArrayDefinition)):
            if _validate_literal_array(node, expected):
                return
    else:
        for given, expected in itertools.product(given_types, expected_type):
            if expected.compare_type(given):
                return

    # validation failed, prepare a meaningful error message
    if len(expected_type) > 1:
        expected_str = f"one of {', '.join(str(i) for i in expected_type)}"
    else:
        expected_str = expected_type[0]

    if len(given_types) == 1 and getattr(given_types[0], "_is_callable", False):
        raise StructureException(
            f"{given_types[0]} cannot be referenced directly, it must be called", node
        )

    if not isinstance(node, (vy_ast.List, vy_ast.Tuple)) and node.get_descendants(
        vy_ast.Name, include_self=True
    ):
        given = given_types[0]
        raise TypeMismatch(f"Given reference has type {given}, expected {expected_str}", node)
    else:
        if len(given_types) == 1:
            given_str = str(given_types[0])
        else:
            types_str = sorted(str(i) for i in given_types)
            given_str = f"{', '.join(types_str[:1])} or {types_str[-1]}"

        raise InvalidType(
            f"Expected {expected_str} but literal can only be cast as {given_str}", node
        )


def get_index_value(node: vy_ast.Index) -> int:
    """
    Return the literal value for a `Subscript` index.

    Arguments
    ---------
    node : vy_ast.Index
        Vyper ast node from the `slice` member of a Subscript node. Must be an
        `Index` object (Vyper does not support `Slice` or `ExtSlice`).

    Returns
    -------
    int
        Literal integer value.
    """

    if not isinstance(node.get("value"), vy_ast.Int):
        if hasattr(node, "value"):
            # even though the subscript is an invalid type, first check if it's a valid _something_
            # this gives a more accurate error in case of e.g. a typo in a constant variable name
            try:
                get_possible_types_from_node(node.value)
            except StructureException:
                # StructureException is a very broad error, better to raise InvalidType in this case
                pass

        raise InvalidType("Subscript must be a literal integer", node)

    if node.value.value <= 0:
        raise ArrayIndexException("Subscript must be greater than 0", node)

    return node.value.value
