from vyper.context.namespace.builtins import (
    add_builtin_units,
    get_meta_types,
)
from vyper.context.namespace.module import (
    add_assignments,
    add_custom_types,
    add_custom_units,
    add_functions,
)
from vyper.exceptions import (
    StructureException,
)


class Namespace(dict):

    """Dictionary subclass that represents the namespace of contract."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._to_introspect = set()
        self._scope_dependencies = {'builtin': None, 'module': "builtin"}

    def __setitem__(self, attr, obj):
        if attr in self:
            raise StructureException(f"'{attr}' has already been declared", obj)
        super().__setitem__(attr, obj)

        # if this object can be introspected, add it to the introspection list
        if hasattr(obj, '_introspect'):
            self._to_introspect.add(attr)

        # if this is a new scope, add it to the scope dependencies
        scope = obj.enclosing_scope
        if scope not in self._scope_dependencies:
            parent_scope = super().__getitem__(scope).enclosing_scope
            self._scope_dependencies[scope] = parent_scope

    def __getitem__(self, key):
        # requesting an item triggers introspection
        item = super().__getitem__(key)
        if key in self._to_introspect:
            self._to_introspect.remove(key)
            item._introspect()
        return item

    def update(self, other):
        for key, value in other.items():
            self[key] = value

    def introspect(self):

        """Triggers introspection on all items within the container."""

        while self._to_introspect:
            key = next(iter(self._to_introspect))
            self.__getitem__(key)

    def items(self):
        raise NotImplementedError

    def keys(self):
        raise NotImplementedError

    def values(self):
        raise NotImplementedError

    def copy(self, scope: str) -> "Namespace":

        """Performs a shallow copy of the object based on the given scope."""
        # TODO documentation

        scopes = set([scope])
        while self._scope_dependencies[scope] is not None:
            scope = self._scope_dependencies[scope]
            scopes.add(scope)

        n = Namespace()
        for key, obj in [(k, v) for k, v in super().items() if v.enclosing_scope in scopes]:
            # all objects in a copied namespace must be introspected
            if key in self._to_introspect:
                self.__getitem__(key)
            n[key] = obj
        n._to_introspect.clear()
        return n


def get_builtin_namespace():

    namespace = Namespace()
    namespace = get_meta_types(namespace)
    namespace = add_builtin_units(namespace)
    # TODO built-in functions
    # TODO reserved keywords

    return namespace


def add_module_namespace(vy_module, namespace):

    module_nodes = vy_module.body.copy()

    module_nodes, namespace = add_custom_units(module_nodes, namespace)
    module_nodes, namespace = add_custom_types(module_nodes, namespace)
    module_nodes, namespace = add_functions(module_nodes, namespace)
    module_nodes, namespace = add_assignments(module_nodes, namespace)

    if module_nodes:
        # TODO expand this to explain why each type is invalid
        print([type(i) for i in module_nodes])
        raise StructureException("Invalid syntax for module-level namespace", module_nodes[0])

    namespace.introspect()
    return namespace
