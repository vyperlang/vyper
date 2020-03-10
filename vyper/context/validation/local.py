from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions import (
    Variable,
    get_definition_from_node,
    get_literal_or_raise,
    get_variable_from_nodes,
)
from vyper.context.types import (
    compare_types,
    get_type_from_node,
    get_type_from_operation,
)
from vyper.context.types.builtins import (
    BoolType,
)
from vyper.context.utils import (
    VyperNodeVisitorBase,
    validate_call_args,
)
from vyper.exceptions import (
    ConstancyViolation,
    ExceptionList,
    FunctionDeclarationException,
    InvalidLiteral,
    InvalidType,
    NamespaceCollision,
    StructureException,
    VariableDeclarationException,
    VyperException,
)


def validate_functions(vy_module):

    """Analyzes a vyper ast and validates the function-level namespaces."""

    err_list = ExceptionList()
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        namespace.enter_scope()
        try:
            FunctionNodeVisitor(node)
        except VyperException as e:
            err_list.append(e)
        finally:
            namespace.exit_scope()

    err_list.raise_if_not_empty()


def check_for_return(node_list: list) -> bool:

    """Checks that all paths within statement body contain a Return node."""

    if next((i for i in node_list if isinstance(i, vy_ast.Return)), None):
        return True
    if_nodes = [i for i in node_list if isinstance(i, vy_ast.If)]
    if not if_nodes:
        return False
    return (
        all(check_for_return(i) for i in (x.body for x in if_nodes)) and
        all(check_for_return(i) for i in (x.orelse for x in if_nodes))
    )


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

    def __init__(self, fn_node):
        self.fn_node = fn_node
        self.func = namespace["self"].get_member(fn_node)
        namespace.update(self.func.arguments)
        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type and not check_for_return(fn_node.body):
            raise FunctionDeclarationException(
                f"{self.func.name} is missing a return statement", fn_node
            )

    def visit_AnnAssign(self, node):
        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )
        name = node.target.id
        if name in namespace["self"].members:
            raise NamespaceCollision(
                "Variable declaration shadows an existing storage variable", node
            )
        var = get_variable_from_nodes(name, node.annotation, node.value)
        namespace[name] = var

    def visit_Assign(self, node):
        if len(node.targets) > 1:
            raise StructureException("Assignment statement must have one target", node.targets[1])

        target_var = get_definition_from_node(node.targets[0])
        if not isinstance(target_var, Variable):
            raise ConstancyViolation(
                f"Cannot assign to {type(target_var).__name__}", node.targets[0]
            )

        value_type = get_type_from_node(node.value)
        compare_types(target_var.type, value_type, node)

    def visit_AugAssign(self, node):

        target_var = get_definition_from_node(node.target)
        if not isinstance(target_var, Variable):
            raise ConstancyViolation(f"Cannot modify {type(target_var).__name__}", node.target)
        target_var.type.validate_numeric_op(node)

        value_type = get_type_from_node(node.value)
        compare_types(target_var.type, value_type, node)

    def visit_Raise(self, node):
        if not node.exc:
            raise StructureException("Raise must have a reason", node)
        if not isinstance(node.exc, vy_ast.Str) or len(node.exc.value) > 32:
            raise InvalidType("Reason must be a string of 32 characters or less", node.exc)

    def visit_Assert(self, node):
        if node.msg:
            if not (
                (isinstance(node.msg, vy_ast.Name) and node.msg.id == "UNREACHABLE") or
                isinstance(node.msg, vy_ast.Str)
            ):
                raise InvalidType("Reason must UNREACHABLE or a string literal", node.msg)

        if isinstance(node.test, (vy_ast.BoolOp, vy_ast.Compare)):
            get_type_from_operation(node)
        elif not isinstance(
            get_type_from_node(node.test),
            (BoolType, vy_ast.NameConstant)
        ):
            raise InvalidType("Assertion test value must be a boolean", node.test)

    def visit_Return(self, node):
        values = node.value
        if values is None:
            if self.func.return_type:
                raise StructureException("Return statement is missing a value", node)
            return
        if values and self.func.return_type is None:
            raise FunctionDeclarationException("Function does not return any values", node)
        compare_types(self.func.return_type, get_type_from_node(values), node)

    def visit_UnaryOp(self, node):
        get_type_from_operation(node)

    def visit_BinOp(self, node):
        get_type_from_operation(node)

    def visit_Compare(self, node):
        get_type_from_operation(node)

    def visit_Call(self, node):
        value = get_definition_from_node(node.func)
        value.get_call_return_type(node)

    def visit_If(self, node):
        test = get_type_from_node(node.test)
        if not isinstance(test, BoolType):
            raise StructureException("If test condition must be a boolean", node.test)
        for n in node.body + node.orelse:
            self.visit(n)

    def visit_For(self, node):
        # TODO constancy
        # For needs a detailed spec, some of the limitations here seem inconsistent

        namespace.enter_scope()

        # iteration over a variable
        if isinstance(node.iter, vy_ast.Name):
            iter_var = namespace[node.iter.id]
            if not isinstance(iter_var.type, list):
                raise InvalidType("Value is not iterable", node.iter)
            target_type = iter_var.type[0]

        # iteration over a literal list
        elif isinstance(node.iter, vy_ast.List):
            iter_values = node.iter.elts
            if not iter_values:
                raise StructureException("Cannot iterate empty array", node.iter)
            target_type = get_type_from_node(node.iter)[0]

        # iteration via range()
        elif isinstance(node.iter, vy_ast.Call):
            if node.iter.func.id != "range":
                raise ConstancyViolation(
                    "Cannot iterate over the result of a function call", node.iter
                )
            validate_call_args(node.iter, (1, 2))

            args = node.iter.args
            target_type = get_type_from_node(args[0])
            if len(args) == 1:
                # range(10)
                get_literal_or_raise(args[0])

            elif isinstance(args[0], (vy_ast.Name, vy_ast.Call)):
                # range(x, x + 10)
                if not hasattr(target_type, 'is_integer'):
                    raise InvalidType("Value is not an integer", args[0])
                if not isinstance(args[1], vy_ast.BinOp) or not isinstance(args[1].op, vy_ast.Add):
                    raise StructureException(
                        "Second element must be the first element plus a literal value", args[0]
                    )
                if args[0] != args[1].left:
                    raise StructureException(
                        "First and second variable must be the same", args[1].left
                    )
                if not isinstance(args[1].right, vy_ast.Int):
                    raise InvalidLiteral("Literal must be an integer", args[1].right)
            else:
                # range(1, 10)
                if args[0].value >= args[1].value:
                    raise InvalidLiteral("Second value must be > first value", args[1])
                # TODO check that args[0] + args[1] doesn't overflow

        else:
            raise StructureException("Invalid syntax for iteration", node.iter)

        var = Variable(node.target.id, target_type)
        namespace[node.target.id] = var

        for n in node.body:
            self.visit(n)
        namespace.exit_scope()

    def visit_Expr(self, node):
        # TODO some types of Expr should raise
        self.visit(node.value)

    def visit_Attribute(self, node):
        get_type_from_node(node)

    def visit_Name(self, node):
        get_type_from_node(node)

    def visit_Subscript(self, node):
        get_type_from_node(node)

    def visit_List(self, node):
        get_type_from_node(node)
