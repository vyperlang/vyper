from vyper import ast as vy_ast
from vyper.context.datatypes.variables import (
    Variable,
    get_rhs_value,
    get_lhs_target,
)
from vyper.exceptions import (
    StructureException,
)


def check_functions(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        FunctionNodeVisitor(node, namespace).visit()


class FunctionNodeVisitor:

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.namespace = namespace.copy('module')
        self.func = namespace[fn_node.name]
        self.namespace.update(self.func.arguments)

    def visit(self):
        for node in self.fn_node.body:
            fn = getattr(self, f'visit_{node.ast_type}', None)
            if fn is None:
                raise StructureException("Unsupported syntax for function-level namespace", node)
            fn(node)

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

    # def visit_Assert(self, node):
    #     pass

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
