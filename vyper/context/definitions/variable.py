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
)
from vyper.context.types import (
    compare_types,
    get_builtin_type,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.exceptions import (
    ArrayIndexException,
    VariableDeclarationException,
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
        else:
            raise

    var_type = get_type_from_annotation(annotation)

    if value:
        value_type = get_type_from_node(value)
        compare_types(var_type, value_type, value)

    return Variable(name, var_type, is_public)


def _from_constant(name, annotation, value):
    var_type = get_type_from_annotation(annotation)

    # TODO should be actual value
    value = get_definition_from_node(value)
    if not isinstance(value, Literal):
        print(type(value))
        raise

    compare_types(var_type, value.type, value)

    return Literal(var_type, value.value)


# TODO
# split Variable into several classes depending on the underlying type.. ?
# a MemberVariable could make sense


class ValueDefinition(BaseDefinition):

    __slots__ = ('type',)

    def __init__(self, name, var_type):
        super().__init__(name)
        self.type = var_type

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
        # TODO actual value
        value = self.validate_index(node.slice.value)

        if isinstance(value, Variable):
            type_ = self.type[0]
            return Variable(self.name, type_)
        elif isinstance(value, Literal):
            self.validate_index(value)
            type_ = self.type[value]
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
    is_constant : bool
        Boolean indicating if the variable is a constant.
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

    def get_member(self, node: vy_ast.Attribute):
        if isinstance(node, vy_ast.FunctionDef):
            name = node.name
        else:
            name = node.attr
        if name not in self.members:
            member_type = self.type.get_member_type(node)
            is_constant = hasattr(self.type, '_readonly_members')
            if not isinstance(member_type, BaseDefinition):
                self.members[name] = Variable(name, member_type, is_constant=is_constant)
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

    # def literal_value(self):
    #     """
    #     Returns the literal assignment value for this variable.

    #     If the initial value was not set, this method will return None. If
    #     the variable type is an array, the returned value will be an array.
    #     """
    #     value = self.value
    #     while isinstance(value, Variable):
    #         value = value.literal_value()
    #     if not isinstance(value, list):
    #         return value
    #     return [i.literal_value() if isinstance(i, Variable) else i for i in value]

    def __repr__(self):
        if not hasattr(self, 'value') or self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"
