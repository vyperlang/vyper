import sys

from vyper.exceptions import (
    StructureException,
)


class Namespace(dict):

    """Dictionary subclass that represents the namespace of contract."""

    def __init__(self):
        super().__init__()
        self._scopes = []

    def __setitem__(self, attr, obj):
        if attr in self:
            obj = super().__getitem__(attr)
            # TODO expand this error message
            raise StructureException(
                f"Namespace collision: '{attr}' already declared as a {type(obj).__name__}",
                obj
            )
        if self._scopes:
            self._scopes[-1].add(attr)
        super().__setitem__(attr, obj)

    def __getitem__(self, key):
        if key not in self:
            raise StructureException(f"Undeclared value: {key}")
        return super().__getitem__(key)

    def enter_scope(self):
        self._scopes.append(set())

    def exit_scope(self):
        for key in self._scopes.pop():
            del self[key]

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)


# simplify access to the Namespace object via python's import machinery
# https://mail.python.org/pipermail/python-ideas/2012-May/014969.html
sys.modules[__name__] = Namespace()
