from typing import (
    Optional,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.bases import (
    BaseDefinition,
)
from vyper.context.definitions.utils import (
    get_definition_from_node,
    get_literal_or_raise,
)
from vyper.context.types import (
    compare_types,
    get_builtin_type,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.exceptions import (
    ArrayIndexException,
)


def get_variable_from_nodes(
    name: str, annotation: vy_ast.VyperNode, value: Optional[vy_ast.VyperNode]
):
    """
    Generates a variable definition object from ast nodes.

    Arguments
    ---------
    name : str
        Name of the variable.
    annotation : VyperNode
        Vyper ast node representing the type of the variable.
    value : VyperNode | None
        Vyper ast node representing the initial value of the variable. Can be
        None if the variable has no initial value assigned.

    Returns
    -------
    Variable object.
    """

    is_public = False
    if isinstance(annotation, vy_ast.Call):
        if annotation.func.id == "constant":
            return _from_constant(name, annotation.args[0], value)
        elif annotation.func.id == "public":
            is_public = True
            annotation = annotation.args[0]

    var_type = get_type_from_annotation(annotation)

    if value:
        value_type = get_type_from_node(value)
        compare_types(var_type, value_type, value)

    return Variable(name, var_type, is_public)


def _from_constant(name, annotation, value):
    var_type = get_type_from_annotation(annotation)

    value = get_literal_or_raise(value)
    compare_types(var_type, value.type, value)

    return Literal(var_type, value.value, name)


# TODO
# split Variable into several classes depending on the underlying type.. ?
# a MemberVariable could make sense


class ValueDefinition(BaseDefinition):

    __slots__ = ('type',)

    def __init__(self, name, var_type):
        super().__init__(name)
        self.type = var_type

    # TODO name is misleading
    def validate_index(self, node):
        value = get_definition_from_node(node)
        compare_types(value.type, get_builtin_type({'int128', 'uint256'}), node)
        if isinstance(value, Literal):
            if value.value >= len(self.type):
                raise ArrayIndexException("Array index out of range", node)
            if value.value < 0:
                raise ArrayIndexException("Array index cannot use negative integers", node)
        return value


class Literal(ValueDefinition):

    __slots__ = ('value',)

    def __init__(self, var_type, value, name=None):
        super().__init__(name or f"{var_type} literal", var_type)
        self.value = value

    def get_index(self, node: vy_ast.Subscript):
        if not isinstance(self.type, list):
            raise

        value = self.validate_index(node.slice.value)

        if isinstance(value, Variable):
            type_ = self.type[0]
            return Variable(self.name, type_)
        elif isinstance(value, Literal):
            type_ = self.type[value.value]
            return Literal(type_, self.value[value.value])
        else:
            raise  # compilerpanic!


class Variable(ValueDefinition):
    """
    A variable definition.

    Variable objects represent the assignment of a type (or types) to a name.
    They hold additional information about the assignment, such as whether it is
    a constant or public. They also provide methods for interaction with the
    underlying type.

    Class attributes
    ----------------
    type : _BaseType | list
        The type object represented by this variable. If the variable is an array,
        this will be a list of types.
    value
        The initial value assigned to this variable. Can be a literal value, another
        variable, a list of one or both, or None.
    members : dict
        A dictionary of definitions for members of this variable. Only used if
        the underlying type is a MemberType.
    is_public : bool
        Boolean indicating if the variable is public.
    """

    __slots__ = ('is_public', 'members')

    def __init__(
        self,
        name: str,
        var_type,
        is_public: bool = False,
    ):
        super().__init__(name, var_type)
        self.is_public = is_public
        self.members = {}

    def add_member(self, attr, var):
        # allows for adding non-variable objects (events, functions)
        if hasattr(var, 'type'):
            self.type.add_member_types(**{attr: var.type})
        self.members[attr] = var

    # TODO update this based on Variable/Literal changes
    def get_member(self, node: vy_ast.Attribute):
        if isinstance(node, vy_ast.FunctionDef):
            name = node.name
        else:
            name = node.attr
        if name not in self.members:
            member_type = self.type.get_member_type(node)
            # is_constant = hasattr(self.type, '_readonly_members')
            if not isinstance(member_type, BaseDefinition):
                self.members[name] = Variable(name, member_type)
            else:
                self.members[name] = member_type
        return self.members[name]

    def get_index(self, node: vy_ast.Subscript):
        if not isinstance(self.type, list):
            type_ = self.type.get_index_type(node.slice.value)
            return Variable(self.name, type_, self.is_public)

        value = self.validate_index(node.slice.value)
        if isinstance(value, Variable):
            type_ = self.type[0]
        elif isinstance(value, Literal):
            type_ = self.type[value.value]
        else:
            print(value, type(value))
            raise  # compilerpanic!
        return Variable(self.name, type_, self.is_public)

    def __repr__(self):
        if not hasattr(self, 'value') or self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"

    def get_signature(self):
        return (), self.type

    def _compare_signature(self, other):
        if not (self.is_public and self.name == other.name and not other.arguments):
            return False
        try:
            compare_types(self.type, other.return_type, None, False)
        except Exception:
            return False
        return True


class EnvironmentVariable(Variable):

    def _compare_signature(self, other):
        # environment variables cannot be public
        return False
