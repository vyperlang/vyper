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
        TypeCheckVisitor(node, namespace)


class TypeCheckVisitor:

    ignored_types = (
        vy_ast.Break,
        vy_ast.Constant,
        vy_ast.Continue,
        vy_ast.Pass,
        vy_ast.Return,
    )

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.namespace = namespace.copy('module')
        self.func = namespace[fn_node.name]
        self.namespace.update(self.func.arguments)
        for node in fn_node.body:
            self.visit(node)

    def visit(self, node):
        if isinstance(node, self.ignored_types):
            return
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

    def visit_Expr(self, node):
        self.visit(node.value)

    def visit_UnaryOp(self, node):
        # TODO what about when node.operand is BinOp ?
        get_value(self.namespace, node.operand).type.validate_op(node)

    def visit_BinOp(self, node):
        nodes = (node.left, node.right)
        _check_operand(self.namespace, node, nodes, "validate_op")

    def visit_Compare(self, node):
        if len(node.ops) != 1:
            raise StructureException("Cannot have a comparison with more than two elements", node)
        _check_operand(self.namespace, node, (node.left, node.comparators[0]), "validate_compare")


def _check_operand(namespace, node, node_list, validation_fn_name):
    literals = [i for i in node_list if isinstance(i, vy_ast.Constant)]
    assigned = [get_value(namespace, i) for i in node_list if i not in literals]

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
        getattr(assigned[0].type, validation_fn_name)(node)
        if assigned[0].type != assigned[1].type:
            raise
        return

    getattr(assigned[0].type, validation_fn_name)(node)
    assigned[0].type.validate_literal(literals[0])
