from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    typecheck,
)
from vyper.context.utils import (
    get_leftmost_id,
)
from vyper.exceptions import (
    VariableDeclarationException,
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

        # TODO cleanup
        node = self._annotation_node
        if isinstance(node, vy_ast.Call) and node.func.id in ("constant", "public"):
            # TODO raise if not module scoped
            setattr(self, f"is_{node.func.id}", True)
            node = node.args[0]
        name = get_leftmost_id(node)
        self.type = typecheck.get_type_from_annotation(self.namespace, node)

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
            value_type = typecheck.get_type_from_node(self.namespace, self._value_node)
            typecheck.compare_types(self.type, value_type, self._value_node)

            if self.is_constant:
                self.value = typecheck.get_value_from_node(self.namespace, self._value_node)
                try:
                    self.literal_value
                except AttributeError:
                    if self.is_constant:
                        raise VariableDeclarationException(
                            "Unable to determine literal value for constant", self._value_node
                        )

    @property
    def enclosing_scope(self):
        return self._annotation_node.enclosing_scope

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
