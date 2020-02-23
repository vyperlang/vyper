from vyper import ast as vy_ast
from vyper.context.datatypes.variables import (
    Variable,
    get_value,
    get_type,
)
from vyper.context.utils import (
    compare_types,
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
        if len(node.targets) > 1:
            raise StructureException("Assignment statement must have one target", node.targets[1])
        target_type = get_type(self.namespace, node.targets[0])
        value_type = get_type(self.namespace, node.value)
        compare_types(target_type, value_type, node)

    def visit_AugAssign(self, node):
        target_type = get_type(self.namespace, node.target)
        target_type.validate_op(node)

        value_type = get_type(self.namespace, node.value)
        compare_types(target_type, value_type, node)

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
        if isinstance(values, vy_ast.Tuple):
            values = values.elts
        compare_types(self.func.return_type, values, node)

    def visit_Expr(self, node):
        self.visit(node.value)

    def visit_UnaryOp(self, node):
        # TODO what about when node.operand is BinOp ?
        get_type(self.namespace, node.operand).validate_op(node)

    def visit_BinOp(self, node):
        nodes = (node.left, node.right)
        _check_operand(self.namespace, node, nodes, "validate_op")

    def visit_Compare(self, node):
        if len(node.ops) != 1:
            raise StructureException("Cannot have a comparison with more than two elements", node)
        _check_operand(self.namespace, node, (node.left, node.comparators[0]), "validate_compare")

    def visit_Call(self, node):
        # TODO
        pass

    def visit_If(self, node):
        self.visit(node.test)
        for n in node.body + node.orelse:
            self.visit(n)

    def visit_For(self, node):
        # TODO
        pass

    def visit_Attribute(self, node):
        get_type(self.namespace, node)

    def visit_Name(self, node):
        get_type(self.namespace, node)

    def visit_Subscript(self, node):
        get_type(self.namespace, node)

    def visit_List(self, node):
        get_type(self.namespace, node)


def _check_operand(namespace, node, node_list, validation_fn_name):
    node_list = [get_type(namespace, i) for i in node_list]

    literals = [i for i in node_list if isinstance(i, vy_ast.Constant)]
    assigned = [i for i in node_list if i not in literals]

    if not assigned:
        # TODO this is wrong for comparisons
        if not isinstance(node.left, (vy_ast.Int, vy_ast.Decimal)):
            raise StructureException(
                f"Invalid literal type for operation: {node.left.ast_type}", node
            )
    else:
        getattr(assigned[0], validation_fn_name)(node)
    compare_types(node_list[0], node_list[1], node)
