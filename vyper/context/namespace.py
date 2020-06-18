from vyper.exceptions import (
    CompilerPanic,
    NamespaceCollision,
    UndeclaredDefinition,
)


class Namespace(dict):
    """
    Dictionary subclass that represents the namespace of a contract.

    Attributes
    ----------
    _scopes : List[Set]
        List of sets containing the key names for each scope
    _has_builtins: bool
        Boolean indicating if constant environment variables have been added
    """

    def __init__(self):
        super().__init__()
        self._scopes = []
        self._has_builtins = False

    def __setitem__(self, attr, obj):
        if attr in self:
            obj = super().__getitem__(attr)
            raise NamespaceCollision(f"'{attr}' has already been declared as a {obj}")

        if self._scopes:
            self._scopes[-1].add(attr)
        super().__setitem__(attr, obj)

    def __getitem__(self, key):
        if key not in self:
            raise UndeclaredDefinition(f"'{key}' has not been declared")
        return super().__getitem__(key)

    def __enter__(self):
        if not self._scopes:
            raise CompilerPanic("Context manager must be invoked via namespace.enter_scope()")

    def __exit__(self, exc_type, exc_value, traceback):
        if not self._scopes:
            raise CompilerPanic("Bad use of namespace as a context manager")
        for key in self._scopes.pop():
            del self[key]

    def enter_builtin_scope(self):
        """
        Add types and builtin values to the namespace.

        Called as a context manager, e.g. `with namespace.enter_builtin_scope():`
        It must be the first scope that is entered prior to type checking.
        """
        # prevent circular import issues
        from vyper.context import environment
        from vyper.context.types import get_types
        from vyper.functions.functions import get_builtin_functions

        if self._scopes:
            raise CompilerPanic("Namespace has a currently active scope")

        if not self._has_builtins:
            # constant builtins are only added once
            self.update(get_types())
            self.update(environment.get_constant_vars())
            self.update(get_builtin_functions())
            self._has_builtins = True

        # mutable builtins are always added
        self._scopes.append(set())
        self.update(environment.get_mutable_vars())
        return self

    def enter_scope(self):
        """
        Enter a new scope within the namespace.

        Called as a context manager, e.g. `with namespace.enter_scope():`
        All items that are added within the context are removed upon exit.
        """
        if not self._scopes:
            raise CompilerPanic("First scope must be entered via `enter_builtin_scope`")
        self._scopes.append(set())
        return self

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)

    def clear(self):
        super().clear()
        self._scopes = []
        self._has_builtins = False


namespace = Namespace()


def get_namespace():
    return namespace
