import contextlib
import contextvars

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

    # -- static namespace infrastructure --

    #: Namespace which surrounds anything, every namespace should be a superset of this one
    base: "Namespace"

    #: ContextVar tracking the current mutable NamespaceBuilder
    builder_context: contextvars.ContextVar

    @staticmethod
    def _new_builder() -> "NamespaceBuilder":
        nsb = NamespaceBuilder(Namespace.base)
        # Can't be included in base, as they get mutated
        nsb.update(environment.get_mutable_vars())
        return nsb

    @staticmethod
    @contextlib.contextmanager
    def new_scope():
        """
        Creates a brand new module scope
        """
        token = Namespace.builder_context.set(Namespace._new_builder())
        try:
            yield
        finally:
            Namespace.builder_context.reset(token)

    @staticmethod
    @contextlib.contextmanager
    def sub_scope():
        """
        Creates a sub-scope of the current scope, making sure mutations do not affect the parent
        """
        copy = Namespace.builder_context.get().copy()
        token = Namespace.builder_context.set(copy)
        try:
            yield
        finally:
            Namespace.builder_context.reset(token)


class NamespaceBuilder(dict):
    """
    Mutable builder that accumulates names during analysis, with scope tracking.
    Use .build() to produce an immutable Namespace when done.
    """

    def __init__(self, other: Namespace):
        super().__init__(other)

    def __eq__(self, other):
        return self is other

    def __setitem__(self, attr, obj):
        self.validate_assignment(attr)
        assert isinstance(attr, str), f"not a string: {attr}"
        super().__setitem__(attr, obj)

    def __getitem__(self, key):
        if key not in self:
            hint = get_levenshtein_error_suggestions(key, self, 0.2)
            raise UndeclaredDefinition(f"'{key}' has not been declared.", hint=hint)
        return super().__getitem__(key)

    def update(self, other):
        for key, value in other.items():
            self.__setitem__(key, value)

    def validate_assignment(self, attr):
        validate_identifier(attr)

        if attr in self:
            prev = super().__getitem__(attr)
            prev_decl = getattr(prev, "decl_node", None)
            msg = f"'{attr}' has already been declared"
            if prev_decl is None:
                msg += f" as a {prev}"
            raise NamespaceCollision(msg, prev_decl=prev_decl)

    def copy(self):
        return NamespaceBuilder(super().copy())

    def build(self) -> Namespace:
        """
        Produce an immutable Namespace from the current contents.
        """
        return Namespace(self)


# initialize class-level state after NamespaceBuilder is defined
Namespace.base = Namespace(
    PRIMITIVE_TYPES
    | environment.get_constant_vars()
    | {k: VarInfo(b) for (k, b) in get_builtin_functions().items()}
)

Namespace.builder_context = contextvars.ContextVar(
    "namespace_builder_context", default=Namespace._new_builder()
)
