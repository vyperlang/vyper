
from vyper.context.namespace.builtins import (
    add_builtin_units,
    get_meta_types,
)
from vyper.context.namespace.globals import (
    add_assignments,
    add_custom_types,
    add_custom_units,
)
from vyper.exceptions import (
    StructureException,
)


class Namespace(dict):

    """Dictionary subclass that represents the namespace of contract."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._to_introspect = set()

    def __setitem__(self, attr, value):
        if attr in self:
            raise StructureException(f"'{attr}' has already been declared", value)
        if hasattr(value, '_introspect'):
            self._to_introspect.add(attr)
        super().__setitem__(attr, value)

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

        for key in self._to_introspect.copy():
            obj = super().__getitem__(key)
            obj._introspect()
            self._to_introspect.remove(key)

    def items(self):
        raise NotImplementedError

    def keys(self):
        raise NotImplementedError

    def values(self):
        raise NotImplementedError


# TODO - builtin > global > local
# environment > module > method

def get_builtin_namespace():

    namespace = Namespace()
    namespace = get_meta_types(namespace)
    namespace = add_builtin_units(namespace)
    # TODO built-in functions
    # TODO reserved keywords

    return namespace


def add_global_namespace(vy_module, namespace):

    global_nodes = vy_module.body.copy()

    global_nodes, namespace = add_custom_units(global_nodes, namespace)
    global_nodes, namespace = add_custom_types(global_nodes, namespace)
    global_nodes, namespace = add_assignments(global_nodes, namespace)

    if global_nodes:
        # TODO expand this to explain why each type is invalid
        raise StructureException("Invalid syntax for global namespace", global_nodes[0])

    namespace.introspect()
    return namespace
