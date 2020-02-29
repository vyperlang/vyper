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
    StructureException,
    VariableDeclarationException,
)


# only validation NOT performed is check for initial value relative to scope
# value only exists on constants, so have to check the node!
def get_variable_from_nodes(namespace, name, annotation, value):
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

    var_type = get_type_from_annotation(namespace, node)

    if value:
        value_type = get_type_from_node(namespace, value)
        compare_types(var_type, value_type, value)
        if 'is_constant' in kwargs:
            kwargs['value'] = get_value_from_node(namespace, value)

    var = Variable(namespace, name, annotation.enclosing_scope, var_type, **kwargs)

    if kwargs.get('is_constant'):
        literal = var.literal_value()
        if literal is None or (isinstance(literal, list) and None in literal):
            raise VariableDeclarationException(
                "Cannot determine literal value for constant", annotation
            )

    return var


class Variable(BaseDefinition):

    # TODO docs, split into several types for members/mappings/etc

    __slots__ = ('value', 'type', 'is_constant', 'is_public', 'members')

    def __init__(
        self,
        namespace,
        name: str,
        enclosing_scope: str,
        var_type,
        value=None,
        is_constant: bool = False,
        is_public: bool = False,
    ):
        super().__init__(namespace, name, enclosing_scope)
        self.type = var_type
        self.is_constant = is_constant
        self.is_public = is_public
        self.value = value
        self.members = {}
        if value is None and isinstance(var_type, list):
            self.value = [
                Variable(
                    namespace,
                    f"{name}[{i}]",
                    enclosing_scope,
                    var_type[i],
                    None,
                    is_constant,
                    is_public
                ) for i in range(len(var_type))]

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
            member = Variable(
                self.namespace,
                name,
                self.enclosing_scope,
                member_type,
                is_constant=hasattr(self.type, '_readonly_members')
            )
            self.members[node.attr] = member
        return self.members[name]

    def get_index(self, node: vy_ast.Subscript):
        if isinstance(self.type, list):
            idx = get_value_from_node(self.namespace, node.slice.value)
            if idx >= len(self.type):
                raise StructureException("Array index out of range", node.slice)
            if idx < 0:
                raise StructureException("Array index cannot use negative integers", node.slice)
            return self.value[idx]
        typ = self.type.get_index_type(node.slice.value)
        return Variable(
            self.namespace,
            self.name,
            self.enclosing_scope,
            typ,
            None,
            self.is_constant,
            self.is_public
        )

    def validate_call(self, node):
        return self.type.validate_call(node)

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

    def __repr__(self):
        if not hasattr(self, 'value') or self.value is None:
            return f"<Variable '{self.name}: {str(self.type)}'>"
        return f"<Variable '{self.name}: {str(self.type)} = {self.value}'>"
