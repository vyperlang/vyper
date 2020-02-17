from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    get_leftmost_id,
)


class Variable:

    # TODO docs

    def __init__(self, namespace, node):
        self.namespace = namespace
        self.node = node

        self.name = self.node.target.id
        self.is_constant = False
        self.is_public = False

        self.value = None

    def introspect(self):
        node = self.node.annotation
        if isinstance(node, vy_ast.Call) and node.func.id in ('constant', 'public'):
            setattr(self, f'is_{node.func.id}', True)
            node = node.args[0]
        name = get_leftmost_id(node)
        self.type = self.namespace[name].get_type(node)
        self.type.introspect()

        # TODO if constant, deduce the value immediately

    def validate(self):
        # TODO this is checking that the assigned value == what's expected
        pass

    def __repr__(self):
        return f"<Variable '{self.name}: {str(self.type)}'>"
