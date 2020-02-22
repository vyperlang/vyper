from vyper import ast as vy_ast
from vyper.context.datatypes.variables import (
    Variable,
    get_rhs_value,
    get_lhs_target,
)
from vyper.exceptions import (
    StructureException,
)


def check_methods(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        FunctionNodeVisitor(node, namespace).check()


class FunctionNodeVisitor:

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.namespace = namespace.copy('module')
        self.func = namespace[fn_node.name]
        self.namespace.update(self.func.arguments)

    def check(self):
        for node in self.fn_node.body:
            getattr(self, f'visit_{node.ast_type}')(node)

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

    # def visit_Delete(self, node):
    #     pass
