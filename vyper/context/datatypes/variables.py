from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    get_leftmost_id,
)
from vyper.exceptions import (
    VariableDeclarationException,
    TypeMismatchException,
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
        # TODO
        # how to handle initial value of storage and memory vars ?

    def validate(self):
        if self.node.value is None:
            self.value = None
        else:
            self.value = validate(self.namespace, self.node.value, self.type)

    def get_item(self, key):
        # TODO
        # create a subclass for values that can be accessed via subscripts (array)
        # also think about member access of structs, or builtins
        if not hasattr(self, 'value'):
            self.validate()
        return self.value[key]

    def __repr__(self):
        return f"<Variable '{self.name}: {str(self.type)}'>"


def validate(namespace, node, validation_type):
    # TODO:
    # subscript - check that reference is valid, compare base type
    # call - ...do the call...
    # folding.. ?
    # types that cannot be assigned to (event, map)
    # does this all belong somewhere else?

    if isinstance(node, vy_ast.List):
        validation_type.validate_for_type(node)
        return [validate(namespace, i, validation_type.base_type) for i in node.elts]

    if isinstance(node, vy_ast.Constant):
        # verify that a literal value is valid for the type
        return validate_constant(node, validation_type)

    if isinstance(node, vy_ast.Name):
        # verify that a variable reference is of the correct type
        return validate_name(namespace, node, validation_type)

    # if isinstance(node, vy_ast.Subscript):




def validate_constant(node: vy_ast.Constant, validation_type):
    validation_type.validate_for_type(node)
    # TODO node.value isn't always what we want!
    return node.value


def validate_name(namespace, node, validation_type):
    var = namespace[node.id]
    if not isinstance(var, Variable):
        raise VariableDeclarationException(f"{node.id} is not a variable", node)
    if var.type != validation_type:
        raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
    return var
