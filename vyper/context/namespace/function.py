from vyper import ast as vy_ast
from vyper.context.datatypes.variables import (
    Variable,
    get_rhs_value,
    get_lhs_target,
    get_value,
)
from vyper.exceptions import (
    StructureException,
    TypeMismatchException,
)


def check_functions(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        FunctionNodeVisitor(node, namespace)


class FunctionNodeVisitor:

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.namespace = namespace.copy('module')
        self.func = namespace[fn_node.name]
        self.namespace.update(self.func.arguments)
        for node in fn_node.body:
            self.visit(node)

    def visit(self, node):
        visitor_fn = getattr(self, f'visit_{node.ast_type}', None)
        if visitor_fn is None:
            raise StructureException(
                f"Unsupported syntax for function-level namespace: {node.ast_type}", node
            )
        visitor_fn(node)

    def visit_AnnAssign(self, node):
        name = node.target.id
        self.namespace[name] = Variable(self.namespace, name, node.annotation, node.value)

    def visit_Assign(self, node):
        target_types = get_lhs_target(self.namespace, node.targets)
        get_rhs_value(self.namespace, node.value, target_types)

    def visit_AugAssign(self, node):
        target_type = get_lhs_target(self.namespace, (node.target,))
        get_rhs_value(self.namespace, node.value, target_type)
        target_type.validate_op(node)

    def visit_Raise(self, node):
        if not node.exc:
            raise StructureException("Raise must have a reason", node)
        if not isinstance(node.exc, vy_ast.Str) or len(node.exc.value) > 32:
            raise StructureException("Reason must be a string of 32 characters or less", node.exc)

    def visit_Assert(self, node):
        self.visit(node.test)

    def visit_Delete(self, node):
        # TODO can we just block this at the AST generation stage?
        raise StructureException("Deleting is not supported, use built-in clear() function", node)

    def visit_Return(self, node):
        values = node.value
        if values is None:
            if self.func.return_type:
                raise StructureException("Return statement is missing a value", node)
            return
        if values and self.func.return_type is None:
            raise StructureException("Function does not return any values", node)
        get_rhs_value(self.namespace, values, self.func.return_type)

    def visit_Pass(self, node):
        return

    def visit_Break(self, node):
        return

    def visit_UnaryOp(self, node):
        # TODO what about when node.operand is BinOp ?
        get_value(self.namespace, node.operand).type.validate_op(node)

    def visit_BinOp(self, node):
        nodes = (node.left, node.right)
        literals = [i for i in nodes if isinstance(i, vy_ast.Constant)]
        assigned = [get_value(self.namespace, i) for i in nodes if i not in literals]

        if not assigned:
            if type(node.left) != type(node.right):  # NOQA: E721
                raise TypeMismatchException(
                    "Cannot perform operation between "
                    f"{node.left.ast_type} and {node.right.ast_type}",
                    node
                )
            if not isinstance(node.left, (vy_ast.Int, vy_ast.Decimal)):
                raise StructureException(
                    f"Invalid literal type for operation: {node.left.ast_type}", node
                )
            return

        if not literals:
            assigned[0].type.validate_op(node)
            if assigned[0].type != assigned[1].type:
                raise

        assigned[0].type.validate_op(node)
        assigned[0].type.validate_literal(literals[0])
