from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.abstract import IntegerAbstractType
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


# TODO constancy checks could be handled here. if the function being evaluated
# is_constant, check that the target of all Call nodes is also constant
class FunctionNodeVisitor(VyperNodeVisitorBase):

    ignored_types = (
        vy_ast.Break,
        vy_ast.Constant,
        vy_ast.Continue,
        vy_ast.Pass,
    )
    scope_name = "function"

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.namespace = namespace
        self.func = namespace["self"].get_member(fn_node.name, fn_node)
        namespace.update(self.func.arguments)
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

        type_definition = get_type_from_annotation(node.annotation)
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
        target.validate_modification(node)

    def visit_AugAssign(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)
        target = get_exact_type_from_node(node.target)
        validate_expected_type(node.value, target)
        target.validate_modification(node)

    def visit_Raise(self, node):
        if not node.exc:
            raise StructureException("Raise must have a reason", node)
        if not isinstance(node.exc, vy_ast.Str) or len(node.exc.value) > 32:
            raise InvalidType("Reason must be a string of 32 characters or less", node.exc)

    def visit_Assert(self, node):
        if node.msg:
            if not (
                (isinstance(node.msg, vy_ast.Name) and node.msg.id == "UNREACHABLE")
                or isinstance(node.msg, vy_ast.Str)
            ):
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
                else:
                    # range(CONSTANT, CONSTANT)
                    if not isinstance(args[1], vy_ast.Int):
                        raise InvalidType("Value must be a literal integer", args[1])
                    validate_expected_type(args[1], IntegerAbstractType())
                    if args[0].value >= args[1].value:
                        raise InvalidLiteral("Second value must be > first value", args[1])

        else:
            # iteration over a variable or literal list
            type_list = [
                i.value_type
                for i in get_possible_types_from_node(node.iter)
                if isinstance(i, ArrayDefinition)
            ]

        if not type_list:
            raise InvalidType("Not an iterable type", node.iter)

        for type_ in type_list:
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

        # TODO only some functions can be called this way
        type_ = get_exact_type_from_node(node.value.func)
        type_.fetch_call_return(node.value)
