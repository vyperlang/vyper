import copy
from typing import Optional

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    ExceptionList,
    FunctionDeclarationException,
    ImmutableViolation,
    InvalidLiteral,
    InvalidOperation,
    InvalidType,
    IteratorException,
    NonPayableViolation,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
    VariableDeclarationException,
    VyperException,
)

# TODO consolidate some of these imports
from vyper.semantics.environment import CONSTANT_ENVIRONMENT_VARS, MUTABLE_ENVIRONMENT_VARS
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.abstract import IntegerAbstractType
from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.function import (
    ContractFunction,
    MemberFunctionDefinition,
    StateMutability,
)
from vyper.semantics.types.indexable.mapping import MappingDefinition
from vyper.semantics.types.indexable.sequence import (
    ArrayDefinition,
    DynamicArrayDefinition,
    TupleDefinition,
)
from vyper.semantics.types.user.event import Event
from vyper.semantics.types.utils import get_type_from_annotation
from vyper.semantics.types.value.address import AddressDefinition
from vyper.semantics.types.value.array_value import StringDefinition
from vyper.semantics.types.value.boolean import BoolDefinition
from vyper.semantics.validation.annotation import StatementAnnotationVisitor
from vyper.semantics.validation.base import VyperNodeVisitorBase
from vyper.semantics.validation.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_possible_types_from_node,
    validate_expected_type,
)


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
                validate_expected_type(msg_node, StringDefinition(1024))
            except TypeMismatch as e:
                raise InvalidType("revert reason must fit within String[1024]") from e


def _validate_address_code_attribute(node: vy_ast.Attribute) -> None:
    value_type = get_exact_type_from_node(node.value)
    if isinstance(value_type, AddressDefinition) and node.attr == "code":
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


class FunctionNodeVisitor(VyperNodeVisitorBase):

    ignored_types = (vy_ast.Break, vy_ast.Constant, vy_ast.Pass)
    scope_name = "function"

    def __init__(
        self, vyper_module: vy_ast.Module, fn_node: vy_ast.FunctionDef, namespace: dict
    ) -> None:
        self.vyper_module = vyper_module
        self.fn_node = fn_node
        self.namespace = namespace
        self.func = fn_node._metadata["type"]
        self.annotation_visitor = StatementAnnotationVisitor(fn_node, namespace)
        self.expr_visitor = _LocalExpressionVisitor()
        namespace.update(self.func.arguments)

        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type:
            if not check_for_terminus(fn_node.body):
                raise FunctionDeclarationException(
                    f"Missing or unmatched return statements in function '{fn_node.name}'", fn_node
                )

        if self.func.mutability == StateMutability.PURE:
            node_list = fn_node.get_descendants(
                vy_ast.Attribute,
                {
                    "value.id": set(CONSTANT_ENVIRONMENT_VARS.keys()).union(
                        set(MUTABLE_ENVIRONMENT_VARS.keys())
                    )
                },
            )
            for node in node_list:
                t = node._metadata.get("type")
                if isinstance(t, ContractFunction) and t.mutability == StateMutability.PURE:
                    # allowed
                    continue
                raise StateAccessViolation(
                    "not allowed to query contract or environment variables in pure functions",
                    node_list[0],
                )
        if self.func.mutability is not StateMutability.PAYABLE:
            node_list = fn_node.get_descendants(
                vy_ast.Attribute, {"value.id": "msg", "attr": "value"}
            )
            if node_list:
                raise NonPayableViolation(
                    "msg.value is not allowed in non-payable functions", node_list[0]
                )

    def visit(self, node):
        super().visit(node)
        self.annotation_visitor.visit(node)

    def visit_AnnAssign(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid assignment", node)

        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )

        type_definition = get_type_from_annotation(node.annotation, DataLocation.MEMORY)
        validate_expected_type(node.value, type_definition)

        try:
            self.namespace[name] = type_definition
        except VyperException as exc:
            raise exc.with_annotation(node) from None
        self.expr_visitor.visit(node.value)

    def visit_Assign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)

        target = get_exact_type_from_node(node.target)
        if isinstance(target, MappingDefinition):
            raise StructureException(
                "Left-hand side of assignment cannot be a HashMap without a key", node
            )

        validate_expected_type(node.value, target)
        target.validate_modification(node, self.func.mutability)

        self.expr_visitor.visit(node.value)
        self.expr_visitor.visit(node.target)

    def visit_AugAssign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)

        target = get_exact_type_from_node(node.target)

        validate_expected_type(node.value, target)
        target.validate_modification(node, self.func.mutability)

        self.expr_visitor.visit(node.value)

    def visit_Raise(self, node):
        if node.exc:
            _validate_revert_reason(node.exc)
            self.expr_visitor.visit(node.exc)

    def visit_Assert(self, node):
        if node.msg:
            _validate_revert_reason(node.msg)
            self.expr_visitor.visit(node.msg)

        try:
            validate_expected_type(node.test, BoolDefinition())
        except InvalidType:
            raise InvalidType("Assertion test value must be a boolean", node.test)
        self.expr_visitor.visit(node.test)

    def visit_Continue(self, node):
        for_node = node.get_ancestor(vy_ast.For)
        if for_node is None:
            raise StructureException("`continue` must be enclosed in a `for` loop", node)

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
            if not isinstance(self.func.return_type, TupleDefinition):
                raise FunctionDeclarationException("Function only returns a single value", node)
            if self.func.return_type.length != len(values):
                raise FunctionDeclarationException(
                    f"Incorrect number of return values: "
                    f"expected {self.func.return_type.length}, got {len(values)}",
                    node,
                )
            for given, expected in zip(values, self.func.return_type.value_type):
                validate_expected_type(given, expected)
        else:
            validate_expected_type(values, self.func.return_type)
        self.expr_visitor.visit(node.value)

    def visit_If(self, node):
        validate_expected_type(node.test, BoolDefinition())
        self.expr_visitor.visit(node.test)
        with self.namespace.enter_scope():
            for n in node.body:
                self.visit(n)
        with self.namespace.enter_scope():
            for n in node.orelse:
                self.visit(n)

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
                validate_expected_type(args[0], IntegerAbstractType())
                type_list = get_possible_types_from_node(args[0])
            else:
                validate_expected_type(args[0], IntegerAbstractType())
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
                    validate_expected_type(args[1], IntegerAbstractType())
                    if args[0].value >= args[1].value:
                        raise StructureException("Second value must be > first value", args[1])

        else:
            # iteration over a variable or literal list
            type_list = [
                i.value_type
                for i in get_possible_types_from_node(node.iter)
                if isinstance(i, (DynamicArrayDefinition, ArrayDefinition))
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

                for name in self.namespace["self"].members[fn_name].recursive_calls:
                    # check for indirect modification
                    fn_node = self.vyper_module.get_children(vy_ast.FunctionDef, {"name": name})[0]
                    if _check_iterator_modification(node.iter, fn_node):
                        raise ImmutableViolation(
                            f"Cannot call '{fn_name}' inside for loop, it may call to '{name}' "
                            f"which potentially modifies iterated storage variable '{iter_name}'",
                            call_node,
                        )
        self.expr_visitor.visit(node.iter)

        for_loop_exceptions = []
        iter_name = node.target.id
        for type_ in type_list:
            # type check the for loop body using each possible type for iterator value
            type_ = copy.deepcopy(type_)
            type_.is_constant = True

            with self.namespace.enter_scope():
                try:
                    self.namespace[iter_name] = type_
                except VyperException as exc:
                    raise exc.with_annotation(node) from None

                try:
                    for n in node.body:
                        self.visit(n)
                    # type information is applied directly because the scope is
                    # closed prior to the call to `StatementAnnotationVisitor`
                    node.target._metadata["type"] = type_
                    return
                except (TypeMismatch, InvalidOperation) as exc:
                    for_loop_exceptions.append(exc)

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
                (f"Casting '{iter_name}' as {type_}: {exc.message}", exc.annotations[0])
                for type_, exc in zip(type_list, for_loop_exceptions)
            ),
        )

    def visit_Expr(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Expressions without assignment are disallowed", node)

        fn_type = get_exact_type_from_node(node.value.func)
        if isinstance(fn_type, Event):
            raise StructureException("To call an event you must use the `log` statement", node)

        if isinstance(fn_type, ContractFunction):
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

        if isinstance(fn_type, MemberFunctionDefinition) and fn_type.is_modifying:
            fn_type.underlying_type.validate_modification(node, self.func.mutability)

        # NOTE: fetch_call_return validates call args.
        return_value = fn_type.fetch_call_return(node.value)
        if (
            return_value
            and not isinstance(fn_type, MemberFunctionDefinition)
            and not isinstance(fn_type, ContractFunction)
        ):
            raise StructureException(
                f"Function '{fn_type._id}' cannot be called without assigning the result", node
            )
        self.expr_visitor.visit(node.value)

    def visit_Log(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Log must call an event", node)
        event = get_exact_type_from_node(node.value.func)
        if not isinstance(event, Event):
            raise StructureException("Value is not an event", node.value)
        event.fetch_call_return(node.value)
        self.expr_visitor.visit(node.value)


class _LocalExpressionVisitor(VyperNodeVisitorBase):
    ignored_types = (vy_ast.Constant, vy_ast.Name)
    scope_name = "function"

    def visit_Attribute(self, node: vy_ast.Attribute) -> None:
        self.visit(node.value)
        _validate_msg_data_attribute(node)
        _validate_address_code_attribute(node)

    def visit_BinOp(self, node: vy_ast.BinOp) -> None:
        self.visit(node.left)
        self.visit(node.right)

    def visit_BoolOp(self, node: vy_ast.BoolOp) -> None:
        for value in node.values:  # type: ignore[attr-defined]
            self.visit(value)

    def visit_Call(self, node: vy_ast.Call) -> None:
        self.visit(node.func)
        for arg in node.args:
            self.visit(arg)
        for kwarg in node.keywords:
            self.visit(kwarg.value)

    def visit_Compare(self, node: vy_ast.Compare) -> None:
        self.visit(node.left)  # type: ignore[attr-defined]
        self.visit(node.right)  # type: ignore[attr-defined]

    def visit_Dict(self, node: vy_ast.Dict) -> None:
        for key in node.keys:
            self.visit(key)
        for value in node.values:
            self.visit(value)

    def visit_Index(self, node: vy_ast.Index) -> None:
        self.visit(node.value)

    def visit_List(self, node: vy_ast.List) -> None:
        for element in node.elements:
            self.visit(element)

    def visit_Subscript(self, node: vy_ast.Subscript) -> None:
        self.visit(node.value)
        self.visit(node.slice)

    def visit_Tuple(self, node: vy_ast.Tuple) -> None:
        for element in node.elements:
            self.visit(element)

    def visit_UnaryOp(self, node: vy_ast.UnaryOp) -> None:
        self.visit(node.operand)  # type: ignore[attr-defined]
