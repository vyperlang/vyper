import copy

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.abstract import IntegerAbstractType
from vyper.context.types.bases import DataLocation
from vyper.context.types.function import ContractFunctionType
from vyper.context.types.indexable.sequence import (
    ArrayDefinition,
    TupleDefinition,
)
from vyper.context.types.utils import get_type_from_annotation
from vyper.context.types.value.boolean import BoolDefinition
from vyper.context.types.value.numeric import Uint256Definition
from vyper.context.validation.base import VyperNodeVisitorBase
from vyper.context.validation.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_possible_types_from_node,
    validate_expected_type,
)
from vyper.exceptions import (
    ConstancyViolation,
    ExceptionList,
    FunctionDeclarationException,
    InvalidLiteral,
    InvalidType,
    NamespaceCollision,
    NonPayableViolation,
    StructureException,
    TypeMismatch,
    VariableDeclarationException,
    VyperException,
)


def validate_functions(vy_module):

    """Analyzes a vyper ast and validates the function-level namespaces."""

    err_list = ExceptionList()
    namespace = get_namespace()
    for node in vy_module.get_children(vy_ast.FunctionDef):
        with namespace.enter_scope():
            try:
                FunctionNodeVisitor(node, namespace)
            except VyperException as e:
                err_list.append(e)

    err_list.raise_if_not_empty()


def _is_terminus_node(node):
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


class FunctionNodeVisitor(VyperNodeVisitorBase):

    ignored_types = (
        vy_ast.Break,
        vy_ast.Constant,
        vy_ast.Continue,
        vy_ast.Pass,
    )
    scope_name = "function"

    def __init__(self, fn_node: vy_ast.FunctionDef, namespace: dict) -> None:
        self.fn_node = fn_node
        self.namespace = namespace
        self.func = namespace["self"].get_member(fn_node.name, fn_node)
        namespace.update(self.func.arguments)

        if not self.func.is_public:
            node_list = fn_node.get_descendants(
                vy_ast.Attribute, {"value.id": "msg", "attr": "sender"}
            )
            if node_list:
                raise ConstancyViolation(
                    "msg.sender is not allowed in private functions", node_list[0]
                )
        if not getattr(self.func, "is_payable", False):
            node_list = fn_node.get_descendants(
                vy_ast.Attribute, {"value.id": "msg", "attr": "value"}
            )
            if node_list:
                raise NonPayableViolation(
                    "msg.value is not allowed in non-payable functions", node_list[0]
                )

        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type:
            if not check_for_terminus(fn_node.body):
                raise FunctionDeclarationException(
                    f"Missing or unmatched return statements in function '{fn_node.name}'", fn_node,
                )

    def visit_AnnAssign(self, node):
        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )
        name = node.target.id
        if name in self.namespace["self"].members:
            raise NamespaceCollision("Variable name shadows an existing storage-scoped value", node)

        type_definition = get_type_from_annotation(node.annotation, DataLocation.MEMORY)
        validate_expected_type(node.value, type_definition)

        try:
            self.namespace[name] = type_definition
        except VyperException as exc:
            raise exc.with_annotation(node) from None

    def visit_Assign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)
        target = get_exact_type_from_node(node.target)
        validate_expected_type(node.value, target)
        if self.func.is_constant and target.location == DataLocation.STORAGE:
            raise ConstancyViolation("Cannot modify storage in a constant function", node)
        target.validate_modification(node)

    def visit_AugAssign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)
        target = get_exact_type_from_node(node.target)
        validate_expected_type(node.value, target)
        if self.func.is_constant and target.location == DataLocation.STORAGE:
            raise ConstancyViolation("Cannot modify storage in a constant function", node)
        target.validate_modification(node)

    def visit_Raise(self, node):
        if not node.exc:
            raise StructureException("Raise must have a reason", node)
        if not isinstance(node.exc, vy_ast.Str) or len(node.exc.value) > 32:
            raise InvalidType("Reason must be a string of 32 characters or less", node.exc)

    def visit_Assert(self, node):
        if node.msg:
            if isinstance(node.msg, vy_ast.Str):
                if not node.msg.value.strip():
                    raise StructureException("Reason string cannot be empty", node.msg)
            elif not (isinstance(node.msg, vy_ast.Name) and node.msg.id == "UNREACHABLE"):
                raise InvalidType("Reason must UNREACHABLE or a string literal", node.msg)

        try:
            validate_expected_type(node.test, BoolDefinition())
        except (InvalidType, TypeMismatch) as exc:
            raise type(exc)("Assertion test value must be a boolean", node.test)

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

    def visit_If(self, node):
        validate_expected_type(node.test, BoolDefinition())
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
                raise ConstancyViolation(
                    "Cannot iterate over the result of a function call", node.iter
                )
            validate_call_args(node.iter, (1, 2))

            args = node.iter.args
            if len(args) == 1:
                # range(CONSTANT)
                if not isinstance(args[0], vy_ast.Num):
                    raise ConstancyViolation("Value must be a literal", node)
                if args[0].value <= 0:
                    raise StructureException("For loop must have at least 1 iteration", args[0])
                validate_expected_type(args[0], Uint256Definition())
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
                            "Second element must be the first element plus a literal value",
                            args[0],
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
                if isinstance(i, ArrayDefinition)
            ]

        if not type_list:
            raise InvalidType("Not an iterable type", node.iter)

        if next((i for i in type_list if isinstance(i, ArrayDefinition)), False):
            raise StructureException("Cannot iterate over a nested list", node.iter)

        if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
            # find references to the iterated node within the for-loop body
            similar_nodes = [
                n
                for n in node.get_descendants(type(node.iter))
                if vy_ast.compare_nodes(node.iter, n)
            ]
            for n in similar_nodes:
                # raise if the node is the target of an assignment statement
                assign = n.get_ancestor((vy_ast.Assign, vy_ast.AugAssign))
                if assign and n in assign.target.get_descendants(include_self=True):
                    raise ConstancyViolation("Cannot alter array during iteration", n)

        for type_ in type_list:
            type_ = copy.deepcopy(type_)
            type_.is_constant = True
            with self.namespace.enter_scope():
                try:
                    self.namespace[node.target.id] = type_
                except VyperException as exc:
                    raise exc.with_annotation(node) from None

                try:
                    for n in node.body:
                        self.visit(n)
                        return
                except TypeMismatch as exc:
                    if len(type_list) == 1:
                        raise exc

        raise TypeMismatch("Could not determine type for iterator values", node)

    def visit_Expr(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Expressions without assignment are disallowed", node)

        fn_type = get_exact_type_from_node(node.value.func)
        if isinstance(fn_type, ContractFunctionType):
            if self.func.is_constant and not fn_type.is_constant:
                raise ConstancyViolation(
                    "Cannot call a non-constant function from a constant function", node
                )

        return_value = fn_type.fetch_call_return(node.value)
        if return_value and not isinstance(fn_type, ContractFunctionType):
            raise StructureException(
                f"Function '{node.value.func}' cannot be called without assigning the result", node
            )
