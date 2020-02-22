from vyper.context.datatypes.variables import (
    Variable,
    get_rhs_value,
    get_lhs_target,
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
