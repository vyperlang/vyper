

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

    def __init__(self, reserved_keys=[]):
        self._reserved_keys = set(reserved_keys)

    def __setitem__(self, attr, value):
        if attr in self:
            raise StructureException(f"'{attr}' has already been declared", value)
        super().__setitem__(attr, value)

    def update(self, other):
        for key, value in other.items():
            self[key] = value

    def introspect(self):

        """Triggers introspection on all items within the container."""

        # TODO - what if we already introspected?
        for obj in self.values():
            if hasattr(obj, 'introspect'):
                obj.introspect()


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

    namespace = add_custom_units(vy_module, namespace)
    namespace = add_custom_types(vy_module, namespace)
    namespace = add_assignments(vy_module, namespace)
    # TODO validate constants
    # TODO check for nodes in global namespace that weren't processed (improper structure)
    namespace.introspect()

    return namespace
