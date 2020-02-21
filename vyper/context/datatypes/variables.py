from vyper import ast as vy_ast
from vyper.context.utils import get_leftmost_id
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

    # TODO docs, slots

    def __init__(self, namespace, name, annotation, value):
        self.namespace = namespace

        self.name = name
        self.annotation = annotation
        self.value = value

        self.is_constant = False
        self.is_public = False

    @property
    def enclosing_scope(self):
        return self.annotation.enclosing_scope

    def _introspect(self):

        node = self.annotation
        if isinstance(node, vy_ast.Call) and node.func.id in ("constant", "public"):
            setattr(self, f"is_{node.func.id}", True)
            node = node.args[0]
        name = get_leftmost_id(node)
        self.type = self.namespace[name].get_type(self.namespace, node)

        if self.value is None:
            # TODO this is commented out because of callargs... need a solution
            # if node.enclosing_scope != "module":
            #     raise
            if self.is_constant:
                raise
            # TODO default values
        else:
            if node.enclosing_scope == "module" and not self.is_constant:
                raise
            if hasattr(self.type, "_no_value"):
                # types that cannot be assigned to
                raise
            self.value = validate(self.namespace, self.value, self.type)

    def get_item(self, key):
        # TODO
        # return a reference object instead of the direct value?
        if not hasattr(self, "value"):
            self._introspect()
        if isinstance(self.value, Variable):
            return self.value.get_item(key)
        return self.value[key]

    def __repr__(self):
        if self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"


def validate(namespace, node, validation_type):
    # TODO:
    # call - ...do the call...
    # folding.. ?
    # does this all belong somewhere else?

    if isinstance(node, vy_ast.List):
        validation_type.validate_literal(node)
        return [validate(namespace, i, validation_type.base_type) for i in node.elts]

    if isinstance(node, vy_ast.Constant):
        # verify that a literal value is valid for the type
        return validate_constant(node, validation_type)

    if isinstance(node, vy_ast.Name):
        # verify that a variable reference is of the correct type
        return validate_name(namespace, node, validation_type)

    if isinstance(node, vy_ast.Subscript):
        return validate_subscript(namespace, node, validation_type)


def validate_constant(node: vy_ast.Constant, validation_type):
    validation_type.validate_literal(node)
    # TODO node.value isn't always what we want!
    return node.value


def validate_name(namespace, node, validation_type):
    var = namespace[node.id]
    if not isinstance(var, Variable):
        raise VariableDeclarationException(f"{node.id} is not a variable", node)
    if var.type != validation_type:
        raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
    return var


def validate_subscript(namespace, node, validation_type):
    base_var = namespace[node.value.id]
    if not isinstance(base_var, Variable):
        raise VariableDeclarationException(f"{node.id} is not a variable", node)

    # validating the slice also validates that this is an ArrayType
    idx = base_var.type.validate_slice(node.slice)
    base_type = base_var.type.base_type
    if base_type != validation_type:
        raise TypeMismatchException(f"Invalid type for assignment: {base_type}", node)

    var = base_var.get_item(idx)

    return var
