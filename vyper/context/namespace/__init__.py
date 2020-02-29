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
        self._scopes = []

    def __setitem__(self, attr, obj):
        if self._scopes:
            self._scopes[-1].add(attr)
        if attr in self:
            obj = super().__getitem__(attr)
            # TODO expand this error message
            raise StructureException(
                f"Namespace collision: '{attr}' is a {obj.enclosing_scope} {type(obj).__name__}",
                obj
            )
        super().__setitem__(attr, obj)

    def enter_scope(self):
        self._scopes.append(set())

    def exit_scope(self):
        for key in self._scopes.pop():
            del self[key]

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)


def get_builtin_namespace():

    namespace = Namespace()
    namespace = get_types(namespace)
    namespace = add_builtin_units(namespace)
    add_builtin_constants(namespace)
    add_environment_variables(namespace)
    add_builtin_functions(namespace)
    # TODO reserved keywords

    return namespace


def add_module_namespace(namespace, vy_module, interface_codes):

    ModuleNodeVisitor(namespace, vy_module, interface_codes)
    return namespace


def validate_functions(namespace, vy_module):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        FunctionNodeVisitor(node, namespace)
