from typing import Optional

from vyper import ast as vy_ast
from vyper.ast.metadata import NodeMetadata
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    CompilerPanic,
    ExceptionList,
    FunctionDeclarationException,
    ImmutableViolation,
    InvalidLiteral,
    InvalidOperation,
    InvalidReference,
    InvalidType,
    IteratorException,
    NonPayableViolation,
    OverflowException,
    StateAccessViolation,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
    UndeclaredDefinition,
    UnknownAttribute,
    VariableDeclarationException,
    VyperException,
    ZeroDivisionException,
)
from vyper.semantics import types
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.analysis.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_expr_info,
    get_possible_types_from_node,
    validate_expected_type,
)
from vyper.semantics.data_locations import DataLocation

# TODO consolidate some of these imports
from vyper.semantics.environment import CONSTANT_ENVIRONMENT_VARS, MUTABLE_ENVIRONMENT_VARS
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types import (
    TYPE_T,
    AddressT,
    BoolT,
    BytesT,
    DArrayT,
    EnumT,
    EventT,
    HashMapT,
    IntegerT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
    VyperType,
    _BytestringT,
    is_type_t,
)
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT, StateMutability
from vyper.semantics.types.utils import type_from_annotation


def validate_functions(vy_module: vy_ast.Module) -> None:
    """Analyzes a vyper ast and validates the function-level namespaces."""

    err_list = ExceptionList()
    namespace = get_namespace()
    for node in vy_module.get_children(vy_ast.FunctionDef):
        with namespace.enter_scope():
            try:
                FunctionNodeVisitor(vy_module, node, namespace)
            except VyperException as e:
                err_list.append(e)

    err_list.raise_if_not_empty()


def _is_terminus_node(node: vy_ast.VyperNode) -> bool:
    if getattr(node, "_is_terminus", None):
        return True
    if isinstance(node, vy_ast.Expr) and isinstance(node.value, vy_ast.Call):
        func = get_exact_type_from_node(node.value.func)
        if getattr(func, "_is_terminus", None):
            return True
    return False


def check_for_terminus(node_list: list) -> bool:
    if next((i for i in node_list if _is_terminus_node(i)), None):
        return True
    for node in [i for i in node_list if isinstance(i, vy_ast.If)][::-1]:
        if not node.orelse or not check_for_terminus(node.orelse):
            continue
        if not check_for_terminus(node.body):
            continue
        return True
    return False


def _check_iterator_modification(
    target_node: vy_ast.VyperNode, search_node: vy_ast.VyperNode
) -> Optional[vy_ast.VyperNode]:
    similar_nodes = [
        n
        for n in search_node.get_descendants(type(target_node))
        if vy_ast.compare_nodes(target_node, n)
    ]

    for node in similar_nodes:
        # raise if the node is the target of an assignment statement
        assign_node = node.get_ancestor((vy_ast.Assign, vy_ast.AugAssign))
        # note the use of get_descendants() blocks statements like
        # self.my_array[i] = x
        if assign_node and node in assign_node.target.get_descendants(include_self=True):
            return node

        attr_node = node.get_ancestor(vy_ast.Attribute)
        # note the use of get_descendants() blocks statements like
        # self.my_array[i].append(x)
        if (
            attr_node is not None
            and node in attr_node.value.get_descendants(include_self=True)
            and attr_node.attr in ("append", "pop", "extend")
        ):
            return node

    return None


def _validate_revert_reason(msg_node: vy_ast.VyperNode) -> None:
    if msg_node:
        if isinstance(msg_node, vy_ast.Str):
            if not msg_node.value.strip():
                raise StructureException("Reason string cannot be empty", msg_node)
        elif not (isinstance(msg_node, vy_ast.Name) and msg_node.id == "UNREACHABLE"):
            try:
                validate_expected_type(msg_node, StringT(1024))
            except TypeMismatch as e:
                raise InvalidType("revert reason must fit within String[1024]") from e


# helpers
def _validate_address_code(node: vy_ast.Attribute, value_type: VyperType) -> None:
    if isinstance(value_type, AddressT) and node.attr == "code":
        # Validate `slice(<address>.code, start, length)` where `length` is constant
        parent = node.get_ancestor()
        if isinstance(parent, vy_ast.Call):
            ok_func = isinstance(parent.func, vy_ast.Name) and parent.func.id == "slice"
            ok_args = len(parent.args) == 3 and isinstance(parent.args[2], vy_ast.Int)
            if ok_func and ok_args:
                return

        raise StructureException(
            "(address).code is only allowed inside of a slice function with a constant length", node
        )


def _validate_msg_data_attribute(node: vy_ast.Attribute) -> None:
    if isinstance(node.value, vy_ast.Name) and node.value.id == "msg" and node.attr == "data":
        parent = node.get_ancestor()
        allowed_builtins = ("slice", "len", "raw_call")
        if not isinstance(parent, vy_ast.Call) or parent.get("func.id") not in allowed_builtins:
            raise StructureException(
                "msg.data is only allowed inside of the slice or len functions", node
            )
        if parent.get("func.id") == "slice":
            ok_args = len(parent.args) == 3 and isinstance(parent.args[2], vy_ast.Int)
            if not ok_args:
                raise StructureException(
                    "slice(msg.data) must use a compile-time constant for length argument", parent
                )


def _validate_msg_value_access(node: vy_ast.Attribute) -> None:
    if isinstance(node.value, vy_ast.Name) and node.attr == "value" and node.value.id == "msg":
        raise NonPayableViolation("msg.value is not allowed in non-payable functions", node)


def _validate_pure_access(node: vy_ast.Attribute, typ: Optional[VyperType] = None) -> None:
    env_vars = set(CONSTANT_ENVIRONMENT_VARS.keys()) | set(MUTABLE_ENVIRONMENT_VARS.keys())
    if isinstance(node.value, vy_ast.Name) and node.value.id in env_vars:
        if isinstance(typ, ContractFunctionT) and typ.mutability == StateMutability.PURE:
            return

        raise StateAccessViolation(
            "not allowed to query contract or environment variables in pure functions", node
        )


def _validate_self_reference(node: vy_ast.Name) -> None:
    if node.id == "self" and not isinstance(node.get_ancestor(), vy_ast.Attribute):
        raise StateAccessViolation("not allowed to query self in pure functions", node)


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
        except InvalidOperation as e:
            err_list.append(e)

    if ret:
        return ret

    raise err_list[0]


class FunctionNodeVisitor(VyperNodeVisitorBase):
    ignored_types = (vy_ast.Pass,)
    scope_name = "function"

    def __init__(
        self, vyper_module: vy_ast.Module, fn_node: vy_ast.FunctionDef, namespace: dict
    ) -> None:
        self.vyper_module = vyper_module
        self.fn_node = fn_node
        self.namespace = namespace
        self.func = fn_node._metadata["type"]
        self.expr_visitor = _ExprVisitor(self.func, self.namespace)

        # allow internal function params to be mutable
        location, is_immutable = (
            (DataLocation.MEMORY, False) if self.func.is_internal else (DataLocation.CALLDATA, True)
        )
        for arg in self.func.arguments:
            namespace[arg.name] = VarInfo(arg.typ, location=location, is_immutable=is_immutable)

        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type:
            if not check_for_terminus(fn_node.body):
                raise FunctionDeclarationException(
                    f"Missing or unmatched return statements in function '{fn_node.name}'", fn_node
                )

        assert self.func.n_keyword_args == len(fn_node.args.defaults)
        for kwarg in self.func.keyword_args:
            self.expr_visitor.visit(kwarg.default_value, kwarg.typ)

    def visit(self, node):
        super().visit(node)

    def visit_AnnAssign(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid assignment", node)

        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )

        typ = type_from_annotation(node.annotation, DataLocation.MEMORY)
        # validate_expected_type(node.value, typ)

        try:
            self.namespace[name] = VarInfo(typ, location=DataLocation.MEMORY)
        except VyperException as exc:
            raise exc.with_annotation(node) from None

        self.expr_visitor.visit(node.target, typ)
        self.expr_visitor.visit(node.value, typ)

    def visit_Assert(self, node):
        if node.msg:
            if isinstance(node.msg, vy_ast.Str):
                if not node.msg.value.strip():
                    raise StructureException("Reason string cannot be empty", node.msg)
            elif not (isinstance(node.msg, vy_ast.Name) and node.msg.id == "UNREACHABLE"):
                try:
                    self.visit(node.msg, StringT(1024))
                except TypeMismatch as e:
                    raise InvalidType("revert reason must fit within String[1024]") from e

        try:
            self.expr_visitor.visit(node.test, BoolT())
        except InvalidType:
            raise InvalidType("Assertion test value must be a boolean", node.test)

    def visit_Assign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)

        target = get_expr_info(node.target)
        if isinstance(target.typ, HashMapT):
            raise StructureException(
                "Left-hand side of assignment cannot be a HashMap without a key", node
            )

        # validate_expected_type(node.value, target.typ)
        target.validate_modification(node, self.func.mutability)

        self.expr_visitor.visit(node.target, target.typ)
        self.expr_visitor.visit(node.value, target.typ)

        value_typ = node.value._metadata.get("type")
        if not target.typ.compare_type(value_typ):
            raise TypeMismatch(f"Expected {target.typ} but got {value_typ} instead", node.value)

    def visit_AugAssign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)

        lhs_info = get_expr_info(node.target)

        # validate_expected_type(node.value, lhs_info.typ)
        lhs_info.validate_modification(node, self.func.mutability)

        self.expr_visitor.visit(node.value, lhs_info.typ)
        self.expr_visitor.visit(node.target, lhs_info.typ)

    def visit_Break(self, node):
        for_node = node.get_ancestor(vy_ast.For)
        if for_node is None:
            raise StructureException("`break` must be enclosed in a `for` loop", node)

    def visit_Continue(self, node):
        for_node = node.get_ancestor(vy_ast.For)
        if for_node is None:
            raise StructureException("`continue` must be enclosed in a `for` loop", node)

    def visit_Expr(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Expressions without assignment are disallowed", node)

        fn_type = get_exact_type_from_node(node.value.func)
        if is_type_t(fn_type, EventT):
            raise StructureException("To call an event you must use the `log` statement", node)

        if is_type_t(fn_type, StructT):
            raise StructureException("Struct creation without assignment is disallowed", node)

        if isinstance(fn_type, ContractFunctionT):
            if (
                fn_type.mutability > StateMutability.VIEW
                and self.func.mutability <= StateMutability.VIEW
            ):
                raise StateAccessViolation(
                    f"Cannot call a mutating function from a {self.func.mutability.value} function",
                    node,
                )

            if (
                self.func.mutability == StateMutability.PURE
                and fn_type.mutability != StateMutability.PURE
            ):
                raise StateAccessViolation(
                    "Cannot call non-pure function from a pure function", node
                )

        if isinstance(fn_type, MemberFunctionT) and fn_type.is_modifying:
            # it's a dotted function call like dynarray.pop()
            expr_info = get_expr_info(node.value.func.value)
            expr_info.validate_modification(node, self.func.mutability)

        # NOTE: fetch_call_return validates call args.
        return_value = fn_type.fetch_call_return(node.value)
        if (
            return_value
            and not isinstance(fn_type, MemberFunctionT)
            and not isinstance(fn_type, ContractFunctionT)
        ):
            raise StructureException(
                f"Function '{fn_type._id}' cannot be called without assigning the result", node
            )
        self.expr_visitor.visit(node.value, fn_type)

    def visit_For(self, node):
        if isinstance(node.iter, vy_ast.Subscript):
            raise StructureException("Cannot iterate over a nested list", node.iter)

        if isinstance(node.iter, vy_ast.Call):
            # iteration via range()
            if node.iter.get("func.id") != "range":
                raise IteratorException(
                    "Cannot iterate over the result of a function call", node.iter
                )
            validate_call_args(node.iter, (1, 2))

            args = node.iter.args
            if len(args) == 1:
                # range(CONSTANT)
                if not isinstance(args[0], vy_ast.Num):
                    raise StateAccessViolation("Value must be a literal", node)
                if args[0].value <= 0:
                    raise StructureException("For loop must have at least 1 iteration", args[0])
                self.expr_visitor.visit(args[0])
                type_list = get_possible_types_from_node(args[0])
            else:
                self.expr_visitor.visit(args[0])
                type_list = get_common_types(*args)
                if not isinstance(args[0], vy_ast.Constant):
                    # range(x, x + CONSTANT)
                    if not isinstance(args[1], vy_ast.BinOp) or not isinstance(
                        args[1].op, vy_ast.Add
                    ):
                        raise StructureException(
                            "Second element must be the first element plus a literal value", args[0]
                        )
                    if not vy_ast.compare_nodes(args[0], args[1].left):
                        raise StructureException(
                            "First and second variable must be the same", args[1].left
                        )
                    if not isinstance(args[1].right, vy_ast.Int):
                        raise InvalidLiteral("Literal must be an integer", args[1].right)
                    if args[1].right.value < 1:
                        raise StructureException(
                            f"For loop has invalid number of iterations ({args[1].right.value}),"
                            " the value must be greater than zero",
                            args[1].right,
                        )
                else:
                    # range(CONSTANT, CONSTANT)
                    if not isinstance(args[1], vy_ast.Int):
                        raise InvalidType("Value must be a literal integer", args[1])
                    self.expr_visitor.visit(args[1])
                    if args[0].value >= args[1].value:
                        raise StructureException("Second value must be > first value", args[1])

                if not type_list:
                    raise TypeMismatch("Iterator values are of different types", node.iter)

        else:
            # iteration over a variable or literal list
            if isinstance(node.iter, vy_ast.List) and len(node.iter.elements) == 0:
                raise StructureException("For loop must have at least 1 iteration", node.iter)

            type_list = [
                i.value_type
                for i in get_possible_types_from_node(node.iter)
                if isinstance(i, (DArrayT, SArrayT))
            ]

        if not type_list:
            raise InvalidType("Not an iterable type", node.iter)

        if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
            # check for references to the iterated value within the body of the loop
            assign = _check_iterator_modification(node.iter, node)
            if assign:
                raise ImmutableViolation("Cannot modify array during iteration", assign)

        # Check if `iter` is a storage variable. get_descendants` is used to check for
        # nested `self` (e.g. structs)
        iter_is_storage_var = (
            isinstance(node.iter, vy_ast.Attribute)
            and len(node.iter.get_descendants(vy_ast.Name, {"id": "self"})) > 0
        )

        if iter_is_storage_var:
            # check if iterated value may be modified by function calls inside the loop
            iter_name = node.iter.attr
            for call_node in node.get_descendants(vy_ast.Call, {"func.value.id": "self"}):
                fn_name = call_node.func.attr

                fn_node = self.vyper_module.get_children(vy_ast.FunctionDef, {"name": fn_name})[0]
                if _check_iterator_modification(node.iter, fn_node):
                    # check for direct modification
                    raise ImmutableViolation(
                        f"Cannot call '{fn_name}' inside for loop, it potentially "
                        f"modifies iterated storage variable '{iter_name}'",
                        call_node,
                    )

                for name in self.namespace["self"].typ.members[fn_name].recursive_calls:
                    # check for indirect modification
                    fn_node = self.vyper_module.get_children(vy_ast.FunctionDef, {"name": name})[0]
                    if _check_iterator_modification(node.iter, fn_node):
                        raise ImmutableViolation(
                            f"Cannot call '{fn_name}' inside for loop, it may call to '{name}' "
                            f"which potentially modifies iterated storage variable '{iter_name}'",
                            call_node,
                        )

        if not isinstance(node.target, vy_ast.Name):
            raise StructureException("Invalid syntax for loop iterator", node.target)

        for_loop_exceptions = []
        iter_name = node.target.id
        for typ in type_list:
            # type check the for loop body using each possible type for iterator value

            with self.namespace.enter_scope():
                try:
                    self.namespace[iter_name] = VarInfo(typ, is_constant=True)
                except VyperException as exc:
                    raise exc.with_annotation(node) from None

                try:
                    with NodeMetadata.enter_typechecker_speculation():
                        for n in node.body:
                            self.visit(n)
                except (TypeMismatch, InvalidOperation) as exc:
                    for_loop_exceptions.append(exc)
                else:
                    self.expr_visitor.visit(node.target, typ)

                    if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
                        typ = get_exact_type_from_node(node.iter)
                        self.expr_visitor.visit(node.iter, typ)
                    if isinstance(node.iter, vy_ast.List):
                        len_ = len(node.iter.elements)
                        self.expr_visitor.visit(node.iter, SArrayT(typ, len_))
                    if isinstance(node.iter, vy_ast.Call) and node.iter.func.id == "range":
                        for a in node.iter.args:
                            self.expr_visitor.visit(a, typ)

                    # success -- do not enter error handling section
                    return

        # failed to find a good type. bail out
        if len(set(str(i) for i in for_loop_exceptions)) == 1:
            # if every attempt at type checking raised the same exception
            raise for_loop_exceptions[0]

        # return an aggregate TypeMismatch that shows all possible exceptions
        # depending on which type is used
        types_str = [str(i) for i in type_list]
        given_str = f"{', '.join(types_str[:1])} or {types_str[-1]}"
        raise TypeMismatch(
            f"Iterator value '{iter_name}' may be cast as {given_str}, "
            "but type checking fails with all possible types:",
            node,
            *(
                (f"Casting '{iter_name}' as {typ}: {exc.message}", exc.annotations[0])
                for typ, exc in zip(type_list, for_loop_exceptions)
            ),
        )

    def visit_If(self, node):
        self.expr_visitor.visit(node.test, BoolT())
        with self.namespace.enter_scope():
            for n in node.body:
                self.visit(n)
        with self.namespace.enter_scope():
            for n in node.orelse:
                self.visit(n)

    def visit_Log(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Log must call an event", node)
        f = get_exact_type_from_node(node.value.func)
        if not is_type_t(f, EventT):
            raise StructureException("Value is not an event", node.value)
        if self.func.mutability <= StateMutability.VIEW:
            raise StructureException(
                f"Cannot emit logs from {self.func.mutability.value.lower()} functions", node
            )
        f.fetch_call_return(node.value)
        node._metadata["type"] = f.typedef
        self.expr_visitor.visit(node.value, f.typedef)

    def visit_Raise(self, node):
        if node.exc:
            _validate_revert_reason(node.exc)

    def visit_Return(self, node):
        values = node.value
        if values is None:
            if self.func.return_type:
                raise FunctionDeclarationException("Return statement is missing a value", node)
            return
        elif self.func.return_type is None:
            raise FunctionDeclarationException("Function does not return any values", node)

        if isinstance(values, vy_ast.Tuple):
            values = values.elements
            if not isinstance(self.func.return_type, TupleT):
                raise FunctionDeclarationException("Function only returns a single value", node)
            if self.func.return_type.length != len(values):
                raise FunctionDeclarationException(
                    f"Incorrect number of return values: "
                    f"expected {self.func.return_type.length}, got {len(values)}",
                    node,
                )
        self.expr_visitor.visit(node.value, self.func.return_type)


def _is_empty_list(node):
    # Checks if a node is a `List` node with an empty list for `elements`,
    # including any nested `List` nodes. ex. `[]` or `[[]]` will return True,
    # [1] will return False.
    if not isinstance(node, vy_ast.List):
        return False

    if not node.elements:
        return True
    return all(_is_empty_list(t) for t in node.elements)


class _ExprVisitor(VyperNodeVisitorBase):
    scope_name = "function"

    def __init__(self, fn_node: ContractFunctionT, namespace: dict):
        self.func = fn_node
        self.namespace = namespace

    def visit(self, node, typ=None):
        # recurse and typecheck in case we are being fed the wrong type for
        # some reason. note that `validate_expected_type` is unnecessary
        # for nodes that already call `get_exact_type_from_node` and
        # `get_possible_types_from_node` because `validate_expected_type`
        # would be calling the same function again.
        # CMC 2023-06-27 would be cleanest to call validate_expected_type()
        # before recursing but maybe needs some refactoring before that
        # can happen.
        super().visit(node, typ)

        # annotate
        if typ:
            node._metadata["type"] = typ

    def visit_Attribute(self, node: vy_ast.Attribute, typ: Optional[VyperType] = None) -> None:
        self.visit(node.value)
        value_type = node.value._metadata["type"]

        name = node.attr
        try:
            s = value_type.get_member(name, node)
            if isinstance(s, VyperType):
                # ex. foo.bar(). bar() is a ContractFunctionT
                derived_typ = s
            # general case. s is a VarInfo, e.g. self.foo
            else:
                derived_typ = s.typ
        except UnknownAttribute:
            if node.get("value.id") != "self":
                raise
            if name in self.namespace:
                raise InvalidReference(
                    f"'{name}' is not a storage variable, it should not be prepended with self",
                    node,
                ) from None

            suggestions_str = get_levenshtein_error_suggestions(name, value_type.members, 0.4)
            raise UndeclaredDefinition(
                f"Storage variable '{name}' has not been declared. {suggestions_str}", node
            ) from None

        if typ and not typ.compare_type(derived_typ):
            raise TypeMismatch(f"Expected {derived_typ} but got {typ} instead", node)

        node._metadata["type"] = derived_typ

        _validate_msg_data_attribute(node)

        if self.func.mutability is not StateMutability.PAYABLE:
            _validate_msg_value_access(node)

        if self.func.mutability == StateMutability.PURE:
            _validate_pure_access(node, typ)

        # value_type = get_exact_type_from_node(node.value)
        _validate_address_code(node, value_type)

    def visit_BinOp(self, node: vy_ast.BinOp, typ: Optional[VyperType] = None) -> None:
        # binary operation: `x + y`
        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)):
            # ad-hoc handling for LShift and RShift, since operands
            # can be different types
            types_list = get_possible_types_from_node(node.left)
        else:
            types_list = get_common_types(node.left, node.right)

        if (
            isinstance(node.op, (vy_ast.Div, vy_ast.Mod))
            and isinstance(node.right, vy_ast.Num)
            and not node.right.value
        ):
            raise ZeroDivisionException(f"{node.op.description} by zero", node)

        _validate_op(node, types_list, "validate_numeric_op")

        if typ:
            for t in types_list:
                if t.compare_type(typ):
                    node._metadata["type"] = typ
                    break
            else:
                raise TypeMismatch(f"Expected {typ} but it is not a possible type", node)
        else:
            typ = types_list.pop()

        self.visit(node.left, typ)

        rtyp = typ
        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)):
            rtyp = get_possible_types_from_node(node.right).pop()

        self.visit(node.right, rtyp)

    def visit_BoolOp(self, node: vy_ast.BoolOp, typ: Optional[VyperType] = None) -> None:
        assert typ == BoolT()  # sanity check
        for value in node.values:
            self.visit(value, BoolT())

    def visit_Call(self, node: vy_ast.Call, typ: Optional[VyperType] = None) -> None:
        self.visit(node.func)
        call_type = node.func._metadata["type"]

        # call_type = get_exact_type_from_node(node.func)
        # except for builtin functions, `get_exact_type_from_node`
        # already calls `validate_expected_type` on the call args
        # and kwargs via `call_type.fetch_call_return`
        # self.visit(node.func, call_type)

        if isinstance(call_type, ContractFunctionT):
            node._metadata["type"] = call_type.fetch_call_return(node)
            # function calls
            if call_type.is_internal:
                self.func.called_functions.add(call_type)
            for arg, typ in zip(node.args, call_type.argument_types):
                self.visit(arg, typ)
            for kwarg in node.keywords:
                # We should only see special kwargs
                typ = call_type.call_site_kwargs[kwarg.arg].typ
                self.visit(kwarg.value, typ)

        elif is_type_t(call_type, EventT):
            # events have no kwargs
            expected_types = call_type.typedef.arguments.values()
            for arg, typ in zip(node.args, expected_types):
                self.visit(arg, typ)
        elif is_type_t(call_type, StructT):
            # struct ctors
            # ctors have no kwargs
            typ = call_type.typedef
            typ.validate_node(node)
            for value, arg_type in zip(
                node.args[0].values, list(call_type.typedef.members.values())
            ):
                self.visit(value, arg_type)

            typ.validate_arg_types(node)
            node._metadata["type"] = typ

        elif isinstance(call_type, MemberFunctionT):
            assert len(node.args) == len(call_type.arg_types)
            for arg, arg_type in zip(node.args, call_type.arg_types):
                self.visit(arg, arg_type)
        else:
            # builtin functions
            arg_types = call_type.infer_arg_types(node)
            # `infer_arg_types` already calls `validate_expected_type`
            for arg, arg_type in zip(node.args, arg_types):
                self.visit(arg, arg_type)
            kwarg_types = call_type.infer_kwarg_types(node)
            for kwarg in node.keywords:
                self.visit(kwarg.value, kwarg_types[kwarg.arg])

            node._metadata["type"] = call_type.fetch_call_return(node)

    def visit_Compare(self, node: vy_ast.Compare, typ: Optional[VyperType] = None) -> None:
        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            # membership in list literal - `x in [a, b, c]`
            if isinstance(node.right, vy_ast.List):
                cmp_typ = get_common_types(node.left, *node.right.elements).pop()
                ltyp = cmp_typ

                rlen = len(node.right.elements)
                rtyp = SArrayT(cmp_typ, rlen)
                self.visit(node.right, rtyp)
            else:
                cmp_typ = get_exact_type_from_node(node.right)
                self.visit(node.right, cmp_typ)
                if isinstance(cmp_typ, EnumT):
                    # enum membership - `some_enum in other_enum`
                    ltyp = cmp_typ
                else:
                    # array membership - `x in my_list_variable`
                    assert isinstance(cmp_typ, (SArrayT, DArrayT))
                    ltyp = cmp_typ.value_type

            self.visit(node.left, ltyp)

        else:
            # ex. a < b
            cmp_typ = get_common_types(node.left, node.right).pop()
            if isinstance(cmp_typ, _BytestringT):
                # for bytestrings, get_common_types automatically downcasts
                # to the smaller common type - that will annotate with the
                # wrong type, instead use get_exact_type_from_node (which
                # resolves to the right type for bytestrings anyways).
                ltyp = get_exact_type_from_node(node.left)
                rtyp = get_exact_type_from_node(node.right)
            else:
                ltyp = rtyp = cmp_typ

            self.visit(node.left, ltyp)
            self.visit(node.right, rtyp)

    def visit_Constant(self, node: vy_ast.Constant, typ: Optional[VyperType] = None) -> None:
        if typ in (BytesT, StringT):
            typ = typ.from_literal(node)
            node._metadata["type"] = typ

        if typ:
            typ.validate_literal(node)

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
                if typ and typ.compare_type(t):
                    node._metadata["type"] = t
                elif not typ:
                    node._metadata["type"] = t
                return

            except VyperException:
                continue

        # failed; prepare a good error message
        if isinstance(node, vy_ast.Num):
            raise OverflowException(
                "Numeric literal is outside of allowable range for number types", node
            )
        raise InvalidLiteral(f"Could not determine type for literal value '{node.value}'", node)

    def visit_Index(self, node: vy_ast.Index, typ: Optional[VyperType] = None) -> None:
        self.visit(node.value, typ)

    def visit_List(self, node: vy_ast.List, typ: Optional[VyperType] = None) -> None:
        if _is_empty_list(node):
            if len(node.elements) > 0:
                # empty nested list literals `[[], []]`
                subtypes = get_possible_types_from_node(node.elements[0])
            else:
                # empty list literal `[]`
                # subtype can be anything
                subtypes = types.PRIMITIVE_TYPES.values()

            for t in subtypes:
                # 1 is minimum possible length for dynarray,
                # can be assigned to anything
                if isinstance(t, VyperType):
                    derived_typ = DArrayT(t, 1)
                    break
                elif isinstance(t, type) and issubclass(t, VyperType):
                    # for typeclasses like bytestrings, use a generic type acceptor
                    derived_typ = DArrayT(t.any(), 1)
                    break
                else:
                    raise CompilerPanic("busted type {t}", node)

            if typ:
                typ.compare_type(derived_typ)

            node._metadata["type"] = derived_typ
            return

        value_types = set()
        for element in node.elements:
            self.visit(element)
            value_types.add(element._metadata["type"])

        if len(value_types) > 1:
            raise InvalidLiteral("Array contains multiple, incompatible types", node)

        value_typ = list(value_types)[0]

        count = len(node.elements)

        sarray_t = SArrayT(value_typ, count)
        darray_t = DArrayT(value_typ, count)

        if typ:
            for t in (sarray_t, darray_t):
                if typ.compare_type(t):
                    derived_typ = t
            else:
                raise TypeMismatch(f"Expected {sarray_t} or {darray_t} but got {typ} instead", node)

        else:
            derived_typ = darray_t

        node._metadata["type"] = derived_typ

    def visit_Name(self, node: vy_ast.Name, typ: Optional[VyperType] = None) -> None:
        if self.func.mutability == StateMutability.PURE:
            _validate_self_reference(node)

        if not typ:
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
                node._metadata["type"] = t
                # when this is a type, we want to lower it
                if isinstance(t, VyperType):
                    # TYPE_T is used to handle cases where a type can occur in call or
                    # attribute conditions, like Enum.foo or MyStruct({...})
                    node._metadata["type"] = TYPE_T(t)
                elif isinstance(t, VarInfo):
                    node._metadata["type"] = t.typ

            except VyperException as exc:
                raise exc.with_annotation(node) from None

        # if not isinstance(typ, TYPE_T):
        #    validate_expected_type(node, typ)

    def visit_Subscript(self, node: vy_ast.Subscript, typ: Optional[VyperType] = None) -> None:
        if isinstance(typ, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        if isinstance(node.value, vy_ast.List):
            possible_base_types = get_possible_types_from_node(node.value)

            for possible_type in possible_base_types:
                if typ.compare_type(possible_type.value_type):
                    base_type = possible_type
                    break
            else:
                # this should have been caught in
                # `get_possible_types_from_node` but wasn't.
                raise TypeCheckFailure(f"Expected {typ} but it is not a possible type", node)

        else:
            base_type = get_exact_type_from_node(node.value)

        base_type.validate_index_type(node.slice.value)

        # get the correct type for the index, it might
        # not be base_type.key_type
        index_types = get_possible_types_from_node(node.slice.value)
        index_type = index_types.pop()

        self.visit(node.slice, index_type)
        self.visit(node.value, base_type)

    def visit_Tuple(self, node: vy_ast.Tuple, typ: Optional[VyperType] = None) -> None:
        if isinstance(typ, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        assert isinstance(typ, TupleT)
        for element, subtype in zip(node.elements, typ.member_types):
            self.visit(element, subtype)

    def visit_UnaryOp(self, node: vy_ast.UnaryOp, typ: Optional[VyperType] = None) -> None:
        self.visit(node.operand, typ)

        types_list = get_possible_types_from_node(node.operand)
        _validate_op(node, types_list, "validate_numeric_op")

        if typ:
            for t in types_list:
                if typ.compare_type(t):
                    break
            else:
                raise TypeMismatch(f"{typ} is not a possible type", node)

    def visit_IfExp(self, node: vy_ast.IfExp, typ: Optional[VyperType] = None) -> None:
        self.visit(node.test, BoolT())

        types_list = get_common_types(node.body, node.orelse)

        if not types_list:
            a = get_possible_types_from_node(node.body)[0]
            b = get_possible_types_from_node(node.orelse)[0]
            raise TypeMismatch(f"Dislike types: {a} and {b}", node)

        for t in types_list:
            if t.compare_type(typ):
                break
        else:
            raise TypeMismatch(f"{typ} is not a possible type", node)
        self.visit(node.body, typ)
        self.visit(node.orelse, typ)
