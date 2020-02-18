from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    get_leftmost_id,
)


# created from AnnAssign
#   * target is a single node and can be a Name, a Attribute or a Subscript.
#   * annotation is the annotation, such as a Str or Name node.
#   * value is a single optional node
#   * simple is a boolean integer set to True for a Name node in target that do not
#     appear in between parenthesis and are hence pure names and not expressions
class Variable:

    # TODO docs

    def __init__(self, namespace, node):
        self.namespace = namespace
        self.node = node

        self.name = self.node.target.id
        self.is_constant = False
        self.is_public = False

        self.value = None

    def _introspect(self):
        node = self.node.annotation
        if isinstance(node, vy_ast.Call) and node.func.id in ('constant', 'public'):
            setattr(self, f'is_{node.func.id}', True)
            node = node.args[0]
        name = get_leftmost_id(node)
        self.type = self.namespace[name].get_type(node)
        if self.is_constant:
            self.validate()
        # TODO if constant, deduce the value immediately

    def validate(self):
        # TODO: checking that the assigned value == what's expected
        # name - check that reference is valid, compare types
        # subscript - check that reference is valid, compare base type
        # call - ...do the call...
        # folding.. ?
        # types that cannot be assigned to (event, map)

        node = self.node.value
        if isinstance(node, (vy_ast.Constant, vy_ast.List)):
            # verify that a literal value is valid for the type
            self.type.validate_for_type(node)

    def __repr__(self):
        return f"<Variable '{self.name}: {str(self.type)}'>"
