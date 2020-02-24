from vyper.context.namespace.builtins import (
    add_builtin_units,
    get_types,
)
from vyper.context.namespace.module import (
    add_variables,
    add_custom_types,
    add_custom_units,
    add_events,
    add_functions,
    add_implemented_interfaces,
)
from vyper.exceptions import (
    StructureException,
)


class Namespace(dict):

    """Dictionary subclass that represents the namespace of contract."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)

    def items(self):
        raise NotImplementedError

    def keys(self):
        raise NotImplementedError

    def values(self):
        raise NotImplementedError

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def copy(self, scope: str) -> "Namespace":

        """Performs a shallow copy of the object based on the given scope."""
        # TODO documentation

        scopes = set([scope])
        while self._scope_dependencies[scope] is not None:
            scope = self._scope_dependencies[scope]
            scopes.add(scope)

        return Namespace(**{k: v for k, v in super().items() if v.enclosing_scope in scopes})


def get_builtin_namespace():

    namespace = Namespace()
    namespace = get_types(namespace)
    namespace = add_builtin_units(namespace)
    # TODO built-in functions
    # TODO reserved keywords

    return namespace


def add_module_namespace(vy_module, namespace, interface_codes):

    module_nodes = vy_module.body.copy()

    # add custom types and units
    module_nodes, namespace = add_custom_units(module_nodes, namespace)
    module_nodes, namespace = add_custom_types(module_nodes, namespace, interface_codes)

    # add assignments
    module_nodes, namespace = add_functions(module_nodes, namespace)
    module_nodes, namespace = add_events(module_nodes, namespace)
    module_nodes, namespace = add_variables(module_nodes, namespace)

    # introspection
    module_nodes, namespace = add_implemented_interfaces(module_nodes, namespace)

    if module_nodes:
        # TODO expand this to explain why each type is invalid
        print([type(i) for i in module_nodes])
        raise StructureException("Unsupported syntax for module-level namespace", module_nodes[0])

    return namespace
