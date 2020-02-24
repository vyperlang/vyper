from vyper import ast as vy_ast
from vyper.context.utils import (
    compare_types,
    get_leftmost_id,
)
from vyper.exceptions import (
    VariableDeclarationException,
    TypeMismatchException,
    StructureException,
    CompilerPanic,
)
from vyper.context import (
    operators,
)


# created from AnnAssign
#   * target is a single node and can be a Name, a Attribute or a Subscript.
#   * annotation is the annotation, such as a Str or Name node.
#   * value is a single optional node
#   * simple is a boolean integer set to True for a Name node in target that do not
#     appear in between parenthesis and are hence pure names and not expressions
class Variable:

    # TODO docs, slots

    def __init__(self, namespace, name: str, annotation, value):
        self.namespace = namespace

        self.name = name
        self._annotation_node = annotation
        self._value_node = value

        self.is_constant = False
        self.is_public = False

    @property
    def enclosing_scope(self):
        return self._annotation_node.enclosing_scope

    def _introspect(self):

        node = self._annotation_node
        if isinstance(node, vy_ast.Call) and node.func.id in ("constant", "public"):
            # TODO raise if not module scoped
            setattr(self, f"is_{node.func.id}", True)
            node = node.args[0]
        name = get_leftmost_id(node)
        self.type = self.namespace[name].get_type(self.namespace, node)

        if self._value_node is None:
            self.value = None
            # TODO this is commented out because of callargs... need a solution
            # if node.enclosing_scope != "module":
            #     raise
            if self.is_constant:
                raise
            # TODO default values
        else:
            if self.enclosing_scope == "module" and not self.is_constant:
                raise
            if hasattr(self.type, "_no_value"):
                # types that cannot be assigned to
                raise
            value_type = get_type(self.namespace, self._value_node)
            compare_types(self.type, value_type, self._value_node)

            if self.is_constant:
                self.value = get_value(self.namespace, self._value_node)
                try:
                    self.literal_value
                except AttributeError:
                    if self.is_constant:
                        raise VariableDeclarationException(
                            "Unable to determine literal value for constant", self._value_node
                        )

    @property
    def literal_value(self):
        """
        Returns the literal assignment value for this variable.

        TODO
         - what if it fails? should raise something other than AttributeError
         - there should be a way to gracefully fall back to value if unavailable
        """
        value = self.value
        if isinstance(value, Variable):
            return value.literal_value
        if isinstance(value, list):
            values = []
            for item in value:
                if isinstance(item, Variable):
                    values.append(item.literal_value)
                else:
                    values.append(item)
            return values
        return value

    def get_item(self, key):
        if not hasattr(self, "value"):
            self._introspect()
        return self.value[key]

    def __repr__(self):
        if not hasattr(self, 'value') or self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"


def get_type(namespace, node):
    """
    Returns the type value of a node without any validation.

    # TODO if the node is a constant, it just returns the node, document this
    """
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_type(namespace, i) for i in node.elts)
    if isinstance(node, (vy_ast.List)):
        if not node.elts:
            return []
        values = [get_type(namespace, i) for i in node.elts]
        for i in values[1:]:
            compare_types(values[0], i, node)
        return values

    if isinstance(node, vy_ast.Constant):
        return node
    if isinstance(node, vy_ast.Name):
        return _get_name(namespace, node).type
    if isinstance(node, (vy_ast.Attribute)):
        return _get_attribute(namespace, node).type
    if isinstance(node, vy_ast.Subscript):
        var, idx = _get_subscript(namespace, node)
        return var.type[idx]
    if isinstance(node, (vy_ast.Op, vy_ast.Compare)):
        return operators.validate_operation(namespace, node)
    raise CompilerPanic(f"Cannot get type from object: {type(node).__name__}")


# TODO - should this be value just like lhs? can they be refactored into a single fn?
def get_value(namespace, node):
    """
    Returns the value of a node.

    Arguments
    ---------
    namespace : Namespace
        The active namespace that this value is being assigned within.

    Returns
    -------
        A literal value, Variable object, or sequence composed of one or both types.
    TODO finish docs
    """

    # TODO:
    # call - ...do the call...
    # attribute
    # folding

    if isinstance(node, vy_ast.List):
        # TODO validate that all types are like?
        return [get_value(namespace, node.elts[i]) for i in range(len(node.elts))]
    if isinstance(node, vy_ast.Tuple):
        return tuple(get_value(namespace, node.elts[i]) for i in range(len(node.elts)))

    if isinstance(node, vy_ast.Constant):
        return node.value

    if isinstance(node, vy_ast.Name):
        return _get_name(namespace, node)

    if isinstance(node, vy_ast.Attribute):
        return _get_attribute(namespace, node)

    if isinstance(node, vy_ast.Subscript):
        base_var, idx = _get_subscript(namespace, node)
        return base_var.get_item(idx)
    # TODO folding
    # if isinstance(node, (vy_ast.BinOp, vy_ast.BoolOp, vy_ast.Compare)):
    #     return operators.validate_operation(namespace, node)
    raise


def _get_name(namespace, node, validation_type=None):
    var = namespace[node.id]
    if not isinstance(var, Variable):
        raise VariableDeclarationException(f"{node.id} is not a variable", node)
    if var.enclosing_scope == "module" and not var.is_constant:
        raise StructureException("Cannot access storage variable directly, use self", node)
    if validation_type and var.type != validation_type:
        raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
    return var


def _get_attribute(namespace, node, validation_type=None):
    if node.value.id == "self":
        var = namespace[node.attr]
        if var.enclosing_scope != "module" or var.is_constant:
            raise StructureException(
                f"'{var.name}' is not a storage variable, do not use self to access it", node
            )
        if validation_type and var.type != validation_type:
            raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
        return var
    raise


def _get_subscript(namespace, node, validation_type=None):
    base_var = get_value(namespace, node.value)  # bug here

    # validating the slice also validates that this is an ArrayType
    idx = base_var.type.validate_slice(node.slice)
    return base_var, idx
