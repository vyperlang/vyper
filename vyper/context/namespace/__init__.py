from vyper.context.namespace.builtins import (
    add_builtin_constants,
    add_builtin_functions,
    add_builtin_units,
    add_environment_variables,
    get_types,
)
from vyper.context.namespace.local import (
    FunctionNodeVisitor,
)
from vyper.context.namespace.module import (
    ModuleNodeVisitor,
)
from vyper.exceptions import (
    StructureException,
)


class Namespace(dict):

    """Dictionary subclass that represents the namespace of contract."""

    def __init__(self):
        super().__init__()
        self._scope_dependencies = {'builtin': None, 'module': "builtin"}

    def __setitem__(self, attr, obj):
        if attr in self:
            obj = super().__getitem__(attr)
            # TODO expand this error message
            raise StructureException(
                f"Namespace collision: '{attr}' is a {obj.enclosing_scope} {type(obj).__name__}",
                obj
            )
        super().__setitem__(attr, obj)

        # if this is a new scope, add it to the scope dependencies
        scope = obj.enclosing_scope
        if scope not in self._scope_dependencies:
            parent_scope = super().__getitem__(scope).enclosing_scope
            self._scope_dependencies[scope] = parent_scope

    def __getitem__(self, key):
        # requesting an item triggers introspection
        try:
            return super().__getitem__(key)
        except KeyError:
            raise StructureException(f"name '{key}' is not defined")

    def add_scope(self, name, parent):
        self._scope_dependencies[name] = parent

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)

    def copy(self, scope: str) -> "Namespace":

        """Performs a shallow copy of the object based on the given scope."""
        # TODO documentation

        namespace_copy = Namespace()

        scopes = set([scope])
        while self._scope_dependencies[scope] is not None:
            namespace_copy.add_scope(scope, self._scope_dependencies[scope])
            scope = self._scope_dependencies[scope]
            scopes.add(scope)

        namespace_copy.update({k: v for k, v in super().items() if v.enclosing_scope in scopes})
        return namespace_copy


def get_builtin_namespace():

    namespace = Namespace()
    namespace = get_types(namespace)
    namespace = add_builtin_units(namespace)
    add_builtin_constants(namespace)
    add_environment_variables(namespace)
    add_builtin_functions(namespace)
    # TODO built-in functions
    # TODO reserved keywords

    return namespace


def add_module_namespace(namespace, vy_module, interface_codes):

    ModuleNodeVisitor(namespace, vy_module, interface_codes)
    return namespace


def validate_functions(namespace, vy_module):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        FunctionNodeVisitor(node, namespace)
