from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    typecheck,
)
from vyper.exceptions import (
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

    var_type = typecheck.get_type_from_annotation(namespace, node)

    if value:
        value_type = typecheck.get_type_from_node(namespace, value)
        typecheck.compare_types(var_type, value_type, value)
        if 'is_constant' in kwargs:
            kwargs['value'] = typecheck.get_value_from_node(namespace, value)

    var = Variable(namespace, name, annotation.enclosing_scope, var_type, **kwargs)

    if kwargs.get('is_constant'):
        literal = var.literal_value()
        if literal is None or (isinstance(literal, list) and None in literal):
            raise VariableDeclarationException(
                "Cannot determine literal value for constant", annotation
            )

    return var


class Variable:

    # TODO docs, slots

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
        self.namespace = namespace
        self.name = name
        self.enclosing_scope = enclosing_scope
        self.type = var_type
        self.is_constant = is_constant
        self.is_public = is_public
        self.value = value

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
