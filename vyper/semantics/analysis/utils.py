import itertools
from typing import Any, Callable, Iterable, List

from vyper import ast as vy_ast
from vyper.exceptions import (
    CompilerPanic,
    InstantiationException,
    InvalidAttribute,
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
from vyper.semantics import types
from vyper.semantics.analysis.base import ExprInfo, Modifiability, ModuleInfo, VarAccess, VarInfo
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.base import TYPE_T, VyperType
from vyper.semantics.types.bytestrings import BytesT, StringT
from vyper.semantics.types.primitives import AddressT, BoolT, BytesM_T, IntegerT
from vyper.semantics.types.subscriptable import DArrayT, SArrayT, TupleT
from vyper.utils import OrderedSet, checksum_encode, int_to_fourbytes


def _validate_op(node, types_list, validation_fn_name):
    if not types_list:
        # TODO raise a better error here: say which types.
        raise TypeMismatch(f"Cannot perform {node.op.description} between dislike types", node)

    ret = []
    err_list = []
    for type_ in types_list:
        _validate_fn = getattr(type_, validation_fn_name)
        try:
            _validate_fn(node)
            ret.append(type_)
        except (InvalidOperation, OverflowException) as e:
            err_list.append(e)

    if ret:
        return ret

    raise err_list[0]


def uses_state(var_accesses: Iterable[VarAccess]) -> bool:
    return any(s.variable.is_state_variable() for s in var_accesses)


class _ExprAnalyser:
    """
    Node type-checker class.

    Type-check logic is implemented in `type_from_<NODE_CLASS>` methods, organized
    according to the Vyper ast node class. Calls to `get_exact_type_from_node` and
    `get_possible_types_from_node` are forwarded to this class, where the node
    class's method resolution order is examined to decide which method to call.
    """

    def __init__(self):
        self.namespace = get_namespace()

    def get_expr_info(self, node: vy_ast.VyperNode, is_callable: bool = False) -> ExprInfo:
        t = self.get_exact_type_from_node(node, include_type_exprs=is_callable)

        # if it's a Name, we have varinfo for it
        if isinstance(node, vy_ast.Name):
            info = self.namespace[node.id]

            if isinstance(info, VarInfo):
                return ExprInfo.from_varinfo(info)

            if isinstance(info, ModuleInfo):
                return ExprInfo.from_moduleinfo(info)

            if isinstance(info, VyperType):
                return ExprInfo(TYPE_T(info))

            raise CompilerPanic(f"unreachable! {info}", node)

        if isinstance(node, vy_ast.Attribute):
            # if it's an Attr, we check the parent exprinfo and
            # propagate the parent exprinfo members down into the new expr
            # note: Attribute(expr value, identifier attr)

            # allow the value node to be a type expr (e.g., MyFlag.A)
            info = self.get_expr_info(node.value, is_callable=True)
            attr = node.attr

            t = info.typ.get_member(attr, node)

            # it's a top-level variable
            if isinstance(t, VarInfo):
                return ExprInfo.from_varinfo(t, attr=attr)

            if isinstance(t, ModuleInfo):
                return ExprInfo.from_moduleinfo(t, attr=attr)

            return info.copy_with_type(t, attr=attr)

        # If it's a Subscript, propagate the subscriptable varinfo
        if isinstance(node, vy_ast.Subscript):
            info = self.get_expr_info(node.value)
            return info.copy_with_type(t)

        return ExprInfo(t)

    def get_exact_type_from_node(self, node, include_type_exprs=False):
        """
        Find exactly one type for a given node.

        Raises StructureException if a single type cannot be determined.

        Arguments
        ---------
        node : VyperNode
            The vyper AST node to find a type for.

        Returns
        -------
        Type object
        """
        types_list = self.get_possible_types_from_node(node, include_type_exprs=include_type_exprs)

        if len(types_list) > 1:
            raise StructureException("Ambiguous type", node)

        return types_list[0]

    def get_possible_types_from_node(self, node, include_type_exprs=False):
        """
        Find all possible types for a given node.
        If the node's metadata contains type information, then that type is returned.

        Arguments
        ---------
        node : VyperNode
            The vyper AST node to find a type for.

        Returns
        -------
        List
            A list of type objects
        """
        # Early termination if typedef is propagated in metadata
        if "type" in node._metadata:
            return [node._metadata["type"]]

        # this method is a perf hotspot, so we cache the result and
        # try to return it if found.
        k = f"possible_types_from_node_{include_type_exprs}"
        if k not in node._metadata:
            fn = self._find_fn(node)
            ret = fn(node)

            if not include_type_exprs:
                invalid = next((i for i in ret if isinstance(i, TYPE_T)), None)
                if invalid is not None:
                    raise InvalidReference(f"not a variable or literal: '{invalid.typedef}'", node)

            if all(isinstance(i, IntegerT) for i in ret):
                # for numeric types, sort according by number of bits descending
                # this ensures literals are cast with the largest possible type
                ret.sort(key=lambda k: (k.bits, not k.is_signed), reverse=True)

            node._metadata[k] = ret

        return node._metadata[k].copy()

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
        is_self_reference = node.get("value.id") == "self"

        # variable attribute, e.g. `foo.bar`
        t = self.get_exact_type_from_node(node.value, include_type_exprs=True)
        name = node.attr

        def _raise_invalid_reference(name, node):
            raise InvalidReference(
                f"'{name}' is not a storage variable, it should not be prepended with self", node
            )

        try:
            s = t.get_member(name, node)

            if isinstance(s, VyperType):
                # ex. foo.bar(). bar() is a ContractFunctionT
                return [s]

            # general case. s is a VarInfo, e.g. self.foo
            if is_self_reference and (s.is_constant or s.is_immutable):
                _raise_invalid_reference(name, node)
            return [s.typ]

        except UnknownAttribute as e:
            if not is_self_reference:
                raise e from None
            if name in self.namespace:
                _raise_invalid_reference(name, node)

            hint = get_levenshtein_error_suggestions(name, t.members, 0.4)
            raise UndeclaredDefinition(
                f"Storage variable '{name}' has not been declared.", node, hint=hint
            ) from None

    def types_from_BinOp(self, node):
        # binary operation: `x + y`
        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)):
            # ad-hoc handling for LShift and RShift, since operands
            # can be different types
            types_list = get_possible_types_from_node(node.left)
            # check rhs is unsigned integer
            validate_expected_type(node.right, IntegerT.unsigneds())
        else:
            types_list = get_common_types(node.left, node.right)

        if (
            isinstance(node.op, (vy_ast.Div, vy_ast.FloorDiv, vy_ast.Mod))
            and isinstance(node.right, vy_ast.Num)
            and not node.right.value
        ):
            raise ZeroDivisionException(f"{node.op.description} by zero", node)

        return _validate_op(node, types_list, "validate_numeric_op")

    def types_from_BoolOp(self, node):
        # boolean operation: `x and y`
        types_list = get_common_types(*node.values)
        _validate_op(node, types_list, "validate_boolean_op")
        return [BoolT()]

    def types_from_Compare(self, node):
        # comparisons, e.g. `x < y`

        # TODO fixme circular import
        from vyper.semantics.types.user import FlagT

        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            # x in y
            left = self.get_possible_types_from_node(node.left)
            right = self.get_possible_types_from_node(node.right)
            if any(isinstance(t, FlagT) for t in left):
                types_list = get_common_types(node.left, node.right)
                _validate_op(node, types_list, "validate_comparator")
                return [BoolT()]

            if any(isinstance(i, SArrayT) for i in left):
                raise InvalidOperation(
                    "Left operand in membership comparison cannot be Array type", node.left
                )
            if any(not isinstance(i, (DArrayT, SArrayT)) for i in right):
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
        return [BoolT()]

    def types_from_ExtCall(self, node):
        call_node = node.value
        return self._find_fn(call_node)(call_node)

    def types_from_StaticCall(self, node):
        call_node = node.value
        return self._find_fn(call_node)(call_node)

    def types_from_Call(self, node):
        # function calls, e.g. `foo()` or `MyStruct()`
        var = self.get_exact_type_from_node(node.func, include_type_exprs=True)
        return_value = var.fetch_call_return(node)
        if return_value:
            if isinstance(return_value, list):
                return return_value
            return [return_value]
        raise InvalidType(f"{var} did not return a value", node)

    def types_from_Constant(self, node):
        # literal value (integer, string, etc)
        types_list = []
        for t in types.PRIMITIVE_TYPES.values():
            try:
                # clarity and perf note: will be better to construct a
                # map from node types to valid vyper types
                if not isinstance(node, t._valid_literal):
                    continue

                # special handling for bytestrings since their
                # class objects are in the type map, not the type itself
                # (worth rethinking this design at some point.)
                if t in (BytesT, StringT):
                    t = t.from_literal(node)

                # any more validation which needs to occur
                t.validate_literal(node)
                types_list.append(t)
            except VyperException:
                continue

        if types_list:
            return types_list

        # failed; prepare a good error message
        if isinstance(node, vy_ast.Num):
            raise OverflowException(
                "Numeric literal is outside of allowable range for number types", node
            )
        raise InvalidLiteral(f"Could not determine type for literal value '{node.value}'", node)

    def types_from_IfExp(self, node):
        validate_expected_type(node.test, BoolT())
        types_list = get_common_types(node.body, node.orelse)

        if not types_list:
            a = get_possible_types_from_node(node.body)[0]
            b = get_possible_types_from_node(node.orelse)[0]
            raise TypeMismatch(f"Dislike types: {a} and {b}", node)

        return types_list

    def types_from_List(self, node):
        # literal array
        if _is_empty_list(node):
            ret = []

            if len(node.elements) > 0:
                # empty nested list literals `[[], []]`
                subtypes = self.get_possible_types_from_node(node.elements[0])
            else:
                # empty list literal `[]`
                # subtype can be anything
                subtypes = types.PRIMITIVE_TYPES.values()

            for t in subtypes:
                # 1 is minimum possible length for dynarray,
                # can be assigned to anything
                if isinstance(t, VyperType):
                    ret.append(DArrayT(t, 1))
                elif isinstance(t, type) and issubclass(t, VyperType):
                    # for typeclasses like bytestrings, use a generic type acceptor
                    ret.append(DArrayT(t.any(), 1))
                else:
                    raise CompilerPanic(f"busted type {t}", node)
            return ret

        types_list = get_common_types(*node.elements)

        if len(types_list) > 0:
            count = len(node.elements)
            ret = []
            ret.extend([SArrayT(t, count) for t in types_list])
            ret.extend([DArrayT(t, count) for t in types_list])
            return ret
        raise InvalidLiteral("Array contains multiple, incompatible types", node)

    def types_from_Name(self, node):
        # variable name, e.g. `foo`
        name = node.id
        if (
            name not in self.namespace
            and "self" in self.namespace
            and name in self.namespace["self"].typ.members
        ):
            raise InvalidReference(
                f"'{name}' is a storage variable, access it as self.{name}", node
            )
        try:
            t = self.namespace[node.id]
            # when this is a type, we want to lower it
            if isinstance(t, VyperType):
                # TYPE_T is used to handle cases where a type can occur in call or
                # attribute conditions, like Flag.foo or MyStruct({...})
                return [TYPE_T(t)]

            return [t.typ]

        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def types_from_Subscript(self, node):
        # index access, e.g. `foo[1]`
        if isinstance(node.value, (vy_ast.List, vy_ast.Subscript)):
            types_list = self.get_possible_types_from_node(node.value)
            ret = []
            for t in types_list:
                t.validate_index_type(node.slice)
                ret.append(t.get_subscripted_type(node.slice))
            return ret

        t = self.get_exact_type_from_node(node.value)
        t.validate_index_type(node.slice)
        return [t.get_subscripted_type(node.slice)]

    def types_from_Tuple(self, node):
        types_list = [self.get_exact_type_from_node(i) for i in node.elements]
        return [TupleT(types_list)]

    def types_from_UnaryOp(self, node):
        # unary operation: `-foo`
        types_list = self.get_possible_types_from_node(node.operand)
        return _validate_op(node, types_list, "validate_numeric_op")


def _is_empty_list(node):
    # Checks if a node is a `List` node with an empty list for `elements`,
    # including any nested `List` nodes. ex. `[]` or `[[]]` will return True,
    # [1] will return False.
    if not isinstance(node, vy_ast.List):
        return False

    if not node.elements:
        return True
    return all(_is_empty_list(t) for t in node.elements)


def _is_type_in_list(obj, types_list):
    # check if a type object is in a list of types
    return any(i.compare_type(obj) for i in types_list)


# NOTE: dead fn
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
    return _ExprAnalyser().get_possible_types_from_node(node, include_type_exprs=True)


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
    return _ExprAnalyser().get_exact_type_from_node(node, include_type_exprs=True)


def get_expr_info(node: vy_ast.ExprNode, is_callable: bool = False) -> ExprInfo:
    if node._expr_info is None:
        node._expr_info = _ExprAnalyser().get_expr_info(node, is_callable)
    return node._expr_info


def get_common_types(*nodes: vy_ast.VyperNode, filter_fn: Callable = None) -> List:
    # this function is a performance hotspot
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
    common_types = _ExprAnalyser().get_possible_types_from_node(nodes[0])

    for item in nodes[1:]:
        new_types = _ExprAnalyser().get_possible_types_from_node(item)

        tmp = []
        for c in common_types:
            for t in new_types:
                if t.compare_type(c) or c.compare_type(t):
                    tmp.append(c)
                    break

        common_types = tmp

    if filter_fn is not None:
        common_types = [i for i in common_types if filter_fn(i)]

    return common_types


# TODO push this into `ArrayT.validate_literal()`
def _validate_literal_array(node, expected):
    # validate that every item within an array has the same type
    if isinstance(expected, SArrayT):
        if len(node.elements) != expected.length:
            return False
    if isinstance(expected, DArrayT):
        if len(node.elements) > expected.length:
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
    if not isinstance(expected_type, tuple):
        expected_type = (expected_type,)

    if isinstance(node, vy_ast.Tuple):
        possible_tuple_types = [t for t in expected_type if isinstance(t, TupleT)]
        for t in possible_tuple_types:
            if len(t.member_types) != len(node.elements):
                continue
            for item_ast, item_type in zip(node.elements, t.member_types):
                try:
                    validate_expected_type(item_ast, item_type)
                    return
                except VyperException:
                    pass
        else:
            # fail block
            pass

    given_types = _ExprAnalyser().get_possible_types_from_node(node)

    if isinstance(node, vy_ast.List):
        # special case - for literal arrays we individually validate each item
        for expected in expected_type:
            if not isinstance(expected, (DArrayT, SArrayT)):
                continue
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

        suggestion_str = ""
        if expected_type[0] == AddressT() and given_types[0] == BytesM_T(20):
            suggestion_str = f" Did you mean {checksum_encode(node.value)}?"

        raise TypeMismatch(
            f"Expected {expected_str} but literal can only be cast as {given_str}.{suggestion_str}",
            node,
        )


def validate_unique_method_ids(functions: List) -> None:
    """
    Check for collisions between the 4byte function selectors
    of each function within a contract.

    Arguments
    ---------
    functions : List[ContractFunctionT]
        A list of ContractFunctionT objects.
    """
    method_ids = [x for i in functions for x in i.method_ids.values()]
    seen = set()
    for method_id in method_ids:
        if method_id in seen:
            collision_str = ", ".join(
                x for i in functions for x in i.method_ids.keys() if i.method_ids[x] == method_id
            )
            collision_hex = int_to_fourbytes(method_id).hex()
            raise StructureException(
                f"Methods produce colliding method ID `0x{collision_hex}`: {collision_str}"
            )
        seen.add(method_id)


def check_modifiability(node: vy_ast.ExprNode, modifiability: Modifiability) -> bool:
    """
    Check if the given node is not more modifiable than the given modifiability.
    """
    if node.is_literal_value or node.has_folded_value:
        return True

    if isinstance(node, (vy_ast.BinOp, vy_ast.Compare)):
        return all(check_modifiability(i, modifiability) for i in (node.left, node.right))

    if isinstance(node, vy_ast.BoolOp):
        return all(check_modifiability(i, modifiability) for i in node.values)

    if isinstance(node, vy_ast.UnaryOp):
        return check_modifiability(node.operand, modifiability)

    if isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        return all(check_modifiability(item, modifiability) for item in node.elements)

    if isinstance(node, vy_ast.Call):
        call_type = get_exact_type_from_node(node.func)

        # structs and interfaces
        if hasattr(call_type, "check_modifiability_for_call"):
            return call_type.check_modifiability_for_call(node, modifiability)

    info = get_expr_info(node)
    return info.modifiability <= modifiability


# TODO: move this into part of regular analysis in `local.py`
def get_expr_writes(node: vy_ast.VyperNode) -> OrderedSet[VarAccess]:
    if "writes_r" in node._metadata:
        return node._metadata["writes_r"]
    ret: OrderedSet = OrderedSet()
    if isinstance(node, vy_ast.ExprNode) and node._expr_info is not None:
        ret = node._expr_info._writes
    for c in node._children:
        ret |= get_expr_writes(c)
    node._metadata["writes_r"] = ret
    return ret


def validate_kwargs(node: vy_ast.Call, members: dict[str, VyperType], typeclass: str):
    # manually validate kwargs for better error messages instead of
    # relying on `validate_call_args`

    seen: dict[str, vy_ast.keyword] = {}
    membernames = list(members.keys())

    # check duplicate kwargs
    for i, kwarg in enumerate(node.keywords):
        # x=5 => kwarg(arg="x", value=Int(5))
        argname = kwarg.arg
        if argname in seen:
            prev = seen[argname]
            raise InvalidAttribute(f"Duplicate {typeclass} argument", prev, kwarg)
        seen[argname] = kwarg

        hint: Any  # mypy kludge
        if argname not in members:
            hint = get_levenshtein_error_suggestions(argname, members, 1.0)
            raise UnknownAttribute(f"Unknown {typeclass} argument.", kwarg, hint=hint)

        expect_name = membernames[i]
        if argname != expect_name:
            # out of order key
            msg = f"{typeclass} keys are required to be in order, but got"
            msg += f" `{argname}` instead of `{expect_name}`."
            hint = "as a reminder, the order of the keys in this"
            hint += f" {typeclass} are {list(members)}"
            raise InvalidAttribute(msg, kwarg, hint=hint)

        expected_type = members[argname]
        validate_expected_type(kwarg.value, expected_type)

    missing = OrderedSet(members.keys()) - OrderedSet(seen.keys())
    if len(missing) > 0:
        msg = f"{typeclass} instantiation missing fields:"
        msg += f" {', '.join(list(missing))}"
        raise InstantiationException(msg, node)
