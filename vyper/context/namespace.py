import sys

from vyper.exceptions import (
    CompilerPanic,
    NamespaceCollision,
    UndeclaredDefinition,
)


class Namespace(dict):

    """Dictionary subclass that represents the namespace of a contract."""

    def __init__(self):
        super().__init__()
        self._scopes = []

    def __setitem__(self, attr, obj):
        if attr in self:
            obj = super().__getitem__(attr)
            raise NamespaceCollision(f"'{attr}' already declared as a {type(obj).__name__}")

        if self._scopes:
            self._scopes[-1].add(attr)

        super().__setitem__(attr, obj)

    def __getitem__(self, key):
        if key not in self:
            raise UndeclaredDefinition(f"Undeclared value: {key}")

        return super().__getitem__(key)

    def __enter__(self):
        if not self._scopes:
            raise CompilerPanic("Context manager must be invoked via namespace.enter_scope()")

    def __exit__(self, exc_type, exc_value, traceback):
        if not self._scopes:
            raise CompilerPanic("Bad use of namespace as a context manager")
        for key in self._scopes.pop():
            del self[key]

    def enter_scope(self):
        self._scopes.append(set())
        return self

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)

    def clear(self):
        super().clear()
        self._scopes.clear()


# simplify access to the Namespace object via python's import machinery
# https://mail.python.org/pipermail/python-ideas/2012-May/014969.html
sys.modules[__name__] = namespace = Namespace()  # type: ignore
namespace.clear()
