from vyper import ast as vy_ast
from vyper.context.utils import get_leftmost_id
from vyper.exceptions import (
    VariableDeclarationException,
    TypeMismatchException,
    StructureException,
    InvalidLiteralException,
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
            self.value = get_rhs_value(self.namespace, self._value_node, self.type)
            if self.is_constant:
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
        if self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"


def get_lhs_target(namespace, targets):
    """
    Validates and returns the left-hand-side type(s) of an assignment.

    Arguments
    ---------
    namespace : Namespace
        The active namespace that this value is being assigned within.

    targets : list
        A list of vyper AST nodes, from the .targets member of an Assign node.

    Returns
    -------
        A type object, or tuple of type objects.
    """
    if len(targets) > 1:
        raise StructureException("Assignment statement must have one target", targets[1])
    target = targets[0]
    if isinstance(target, vy_ast.Name):
        return _get_name(namespace, target).type
    if isinstance(target, vy_ast.Subscript):
        var, idx = _get_subscript(namespace, target)
        return var.type.base_type[idx]
    if isinstance(target, vy_ast.Tuple):
        return tuple(get_lhs_target(namespace, (i,)) for i in target.elts)


def get_rhs_value(namespace, node, validation_type):
    """
    Validates and returns the right-hand-side value(s) of an assignment.

    Arguments
    ---------
    namespace : Namespace
        The active namespace that this value is being assigned within.

    node : Constant | List | Name | Subscript
        A vyper AST node, from the .value member of an Assign or AnnAssign node.

    validation_type : _BaseType | Sequence
        A type object, or sequence of type objects, that the value is validated
        against before returning

    Returns
    -------
        A literal value, Variable object, or list composed of one or both types.
    """

    # TODO:
    # call - ...do the call...
    # folding.. ?
    # how to handle recursion, right now it raises with AttributeError: "literal_value"
    # does this all belong somewhere else?

    if isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        if not hasattr(validation_type, '__len__'):
            raise StructureException(f"Cannot assign multiple values to {validation_type}", node)
        if len(node.elts) != len(validation_type):
            raise InvalidLiteralException(
                "Invalid length for literal array, expected "
                f"{len(node.elts)} got {len(validation_type)}",
                node
            )
        return [
            get_rhs_value(namespace, node.elts[i], validation_type[i])
            for i in range(len(node.elts))
        ]

    if isinstance(node, vy_ast.Constant):
        # verify that a literal value is valid for the type
        validation_type.validate_literal(node)
        return node.value

    if isinstance(node, vy_ast.Name):
        # verify that a variable reference is of the correct type
        return _get_name(namespace, node, validation_type)

    if isinstance(node, vy_ast.Subscript):
        base_var, idx = _get_subscript(namespace, node, validation_type)
        base_type = base_var.type.base_type
        if base_type[idx] != validation_type:
            raise TypeMismatchException(f"Invalid type for assignment: {base_type}", node)
        return base_var.get_item(idx)
    raise


def _get_name(namespace, node, validation_type=None):
    var = namespace[node.id]
    if not isinstance(var, Variable):
        raise VariableDeclarationException(f"{node.id} is not a variable", node)
    if validation_type and var.type != validation_type:
        raise TypeMismatchException(f"Invalid type for assignment: {var.type}", node)
    return var


def _get_subscript(namespace, node, validation_type=None):
    base_var = _get_name(namespace, node.value)

    # validating the slice also validates that this is an ArrayType
    idx = base_var.type.validate_slice(node.slice)
    return base_var, idx
