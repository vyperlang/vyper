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
    get_value_from_node,
)
from vyper.context.types import (
    compare_types,
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

    kwargs = {}

    node = annotation
    while isinstance(node, vy_ast.Call) and node.func.id in ("constant", "public"):
        if annotation.enclosing_scope != "module":
            raise VariableDeclarationException(
                f"Only module-scoped variables can be {node.func.id}", node
            )
        kwargs[f"is_{node.func.id}"] = True
        node = node.args[0]

    if 'is_constant' in kwargs and 'is_public' in kwargs:
        raise VariableDeclarationException("Variable cannot be constant and public", annotation)

    var_type = get_type_from_annotation(node)

    if value:
        value_type = get_type_from_node(value)
        compare_types(var_type, value_type, value)
        if 'is_constant' in kwargs:
            kwargs['value'] = get_value_from_node(value)

    var = Variable(name, var_type, **kwargs)

    if kwargs.get('is_constant'):
        literal = var.literal_value()
        if literal is None or (isinstance(literal, list) and None in literal):
            raise VariableDeclarationException(
                "Cannot determine literal value for constant", annotation
            )

    return var


# TODO
# split Variable into several classes depending on the underlying type.. ?
# a MemberVariable could make sense

class Variable(BaseDefinition):
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

    __slots__ = ('value', 'type', 'is_constant', 'is_public', 'members')

    def __init__(
        self,
        name: str,
        var_type,
        value=None,
        is_constant: bool = False,
        is_public: bool = False,
    ):
        super().__init__(name)
        self.type = var_type
        self.is_constant = is_constant
        self.is_public = is_public
        self.value = value
        self.members = {}

        # if the variable is an array, generate Variables for each item within it
        if value is None and isinstance(var_type, list):
            self.value = [
                Variable(f"{name}[{i}]", var_type[i], None, is_constant, is_public)
                for i in range(len(var_type))
            ]

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
        if isinstance(self.type, list):
            idx = get_value_from_node(node.slice.value)
            if idx >= len(self.type):
                raise ArrayIndexException("Array index out of range", node.slice)
            if idx < 0:
                raise ArrayIndexException("Array index cannot use negative integers", node.slice)
            return self.value[idx]
        typ = self.type.get_index_type(node.slice.value)
        return Variable(self.name, typ, None, self.is_constant, self.is_public)

    def literal_value(self):
        """
        Returns the literal assignment value for this variable.

        If the initial value was not set, this method will return None. If
        the variable type is an array, the returned value will be an array.
        """
        value = self.value
        while isinstance(value, Variable):
            value = value.literal_value()
        if not isinstance(value, list):
            return value
        return [i.literal_value() if isinstance(i, Variable) else i for i in value]

    def __repr__(self):
        if not hasattr(self, 'value') or self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"
