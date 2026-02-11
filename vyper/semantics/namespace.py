import contextlib
import contextvars

from vyper.ast.identifiers import validate_identifier
from vyper.builtins.functions import get_builtin_functions
from vyper.exceptions import CompilerPanic, NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.types import PRIMITIVE_TYPES


class Namespace(dict):
    """
    Immutable namespace object representing a contract's resolved names.
    Do note however that values stored in the namespace are not necessarily immutable !

    Map from str to
      VarInfo         - variable/builtin function bindings
      VyperType       - type instances (e.g. BoolT(), AddressT(), StructT, EventT, FlagT)
      type[VyperType] - type classes used as constructors (e.g. BytesT, StringT, DArrayT)
      ModuleInfo      - imported module bindings
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

    # -- immutable update methods --

    def _validate_assignment(self, attr: str) -> None:
        """Validate that a name can be assigned."""
        validate_identifier(attr)

        if attr in self:
            prev = super().__getitem__(attr)
            prev_decl = getattr(prev, "decl_node", None)
            msg = f"'{attr}' has already been declared"
            if prev_decl is None:
                msg += f" as a {prev}"
            raise NamespaceCollision(msg, prev_decl=prev_decl)

    def with_item(self, key: str, value) -> "Namespace":
        """Return a new Namespace with the key-value pair added."""
        self._validate_assignment(key)
        assert isinstance(key, str), f"not a string: {key}"
        new_data = dict(self)
        new_data[key] = value
        return Namespace(new_data)

    def with_items(self, items: dict) -> "Namespace":
        """Return a new Namespace with multiple items added."""
        new_ns = self
        for key, value in items.items():
            new_ns = new_ns.with_item(key, value)
        return new_ns

    # -- static namespace infrastructure --

    #: Namespace which surrounds anything, every namespace should be a superset of this one
    base: "Namespace"

    #: ContextVar tracking the current immutable Namespace
    context: contextvars.ContextVar

    @staticmethod
    def _new_namespace() -> "Namespace":
        """Create a new namespace initialized with base + mutable vars."""
        return Namespace.base.with_items(environment.get_mutable_vars())

    @staticmethod
    @contextlib.contextmanager
    def new_scope():
        """
        Creates a brand new module scope
        """
        token = Namespace.context.set(Namespace._new_namespace())
        try:
            yield
        finally:
            Namespace.context.reset(token)

    @staticmethod
    @contextlib.contextmanager
    def sub_scope():
        """
        Creates a sub-scope of the current scope, making sure mutations do not affect the parent
        """
        token = Namespace.context.set(Namespace.context.get())
        try:
            yield
        finally:
            Namespace.context.reset(token)


# initialize class-level state
Namespace.base = Namespace(
    PRIMITIVE_TYPES
    | environment.get_constant_vars()
    | {k: VarInfo(b) for (k, b) in get_builtin_functions().items()}
)

Namespace.context = contextvars.ContextVar("namespace_context", default=Namespace._new_namespace())
