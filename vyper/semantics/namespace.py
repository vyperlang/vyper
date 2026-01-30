import contextlib

from vyper.ast.identifiers import validate_identifier
from vyper.builtins.functions import get_builtin_functions
from vyper.exceptions import CompilerPanic, NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.types import PRIMITIVE_TYPES


# TODO: Add precise key and value types
class Namespace(dict):
    """
    Immutable namespace object representing a contract's resolved names.
    Produced by NamespaceBuilder after analysis is complete.
    """

    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        if key not in self:
            hint = get_levenshtein_error_suggestions(key, self, 0.2)
            raise UndeclaredDefinition(f"'{key}' has not been declared.", hint=hint)
        return super().__getitem__(key)

    def __setitem__(self, attr, obj):
        raise CompilerPanic("Cannot modify an immutable Namespace")

    def __delitem__(self, key):
        raise CompilerPanic("Cannot modify an immutable Namespace")

    def update(self, other):
        raise CompilerPanic("Cannot modify an immutable Namespace")

    def clear(self):
        raise CompilerPanic("Cannot modify an immutable Namespace")

    def __reduce__(self):
        return (Namespace, (dict(self),))


"""
Namespace which surrounds anything, every namespace should be a superset of this one
"""
base_namespace: Namespace = Namespace(
    PRIMITIVE_TYPES
    | environment.get_constant_vars()
    | {k: VarInfo(b) for (k, b) in get_builtin_functions().items()}
)


class NamespaceBuilder(dict):
    """
    Mutable builder that accumulates names during analysis, with scope tracking.
    Use .build() to produce an immutable Namespace when done.

    Attributes
    ----------
    _scopes : List[Set]
        List of sets containing the key names for each scope
    """

    _scopes: list[set]

    def __init__(self, other: Namespace):
        super().__init__(other)
        self._scopes = []

    def __eq__(self, other):
        return self is other

    def __setitem__(self, attr, obj):
        if self._scopes:
            self.validate_assignment(attr)
            self._scopes[-1].add(attr)
        assert isinstance(attr, str), f"not a string: {attr}"
        super().__setitem__(attr, obj)

    def __getitem__(self, key):
        if key not in self:
            hint = get_levenshtein_error_suggestions(key, self, 0.2)
            raise UndeclaredDefinition(f"'{key}' has not been declared.", hint=hint)
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
        """
        Enter a new scope within the namespace.

        Called as a context manager, e.g. `with namespace.enter_scope():`
        All items that are added within the context are removed upon exit.
        """
        # NOTE cyclic imports!
        from vyper.semantics import environment

        self._scopes.append(set())

        if len(self._scopes) == 1:
            # add mutable vars (`self`) to the initial scope
            self.update(environment.get_mutable_vars())

        return self

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)

    # TODO: Remove, instead of clearing, just make a new one
    def clear(self):
        super().clear()
        self.__init__(base_namespace)

    def validate_assignment(self, attr):
        validate_identifier(attr)

        if attr in self:
            prev = super().__getitem__(attr)
            prev_decl = getattr(prev, "decl_node", None)
            msg = f"'{attr}' has already been declared"
            if prev_decl is None:
                msg += f" as a {prev}"
            raise NamespaceCollision(msg, prev_decl=prev_decl)

    def build(self) -> Namespace:
        """
        Produce an immutable Namespace from the current contents.
        """
        return Namespace(self)


# TODO: Rename to get_namespace_builder():
def get_namespace():
    """
    Get the global namespace builder object.
    """
    global _namespace
    try:
        return _namespace
    except NameError:
        _namespace = NamespaceBuilder(base_namespace)
        return _namespace


@contextlib.contextmanager
def override_global_namespace(ns):
    global _namespace
    tmp = _namespace
    try:
        # clobber global namespace
        _namespace = ns
        yield
    finally:
        # unclobber
        _namespace = tmp
