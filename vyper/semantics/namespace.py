import contextlib
import contextvars

from vyper.ast.identifiers import validate_identifier
from vyper.builtins.functions import get_builtin_functions
from vyper.exceptions import NamespaceCollision, UndeclaredDefinition
from vyper.semantics import environment
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.types import PRIMITIVE_TYPES


class Namespace:
    """
    Immutable namespace object representing a contract's resolved names.
    Do note however that values stored in the namespace are not necessarily immutable !

    Map from str to
      VarInfo         - variable/builtin function bindings
      VyperType       - type instances (e.g. BoolT(), AddressT(), StructT, EventT, FlagT)
      type[VyperType] - type classes used as constructors (e.g. BytesT, StringT, DArrayT)
      ModuleInfo      - imported module bindings
    """

    _dict: dict  # [str, VarInfo | VyperType | type[VyperType] | ModuleInfo]

    def __init__(self, data: dict):
        self._dict = data

    def __eq__(self, other):
        return self is other

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __getitem__(self, key):
        if key not in self._dict:
            hint = get_levenshtein_error_suggestions(key, self._dict, 0.2)
            raise UndeclaredDefinition(f"'{key}' has not been declared.", hint=hint)
        return self._dict[key]

    def items(self):
        return self._dict.items()

    def __reduce__(self):
        return (Namespace, (self._dict,))

    # -- immutable update methods --

    def _validate_assignment(self, attr: str) -> None:
        """Validate that a name can be assigned."""
        validate_identifier(attr)

        if attr in self:
            prev = self._dict[attr]
            prev_decl = getattr(prev, "decl_node", None)
            msg = f"'{attr}' has already been declared"
            if prev_decl is None:
                msg += f" as a {prev}"
            raise NamespaceCollision(msg, prev_decl=prev_decl)

    def with_item(self, key: str, value) -> "Namespace":
        """Return a new Namespace with the key-value pair added."""
        self._validate_assignment(key)
        assert isinstance(key, str), f"not a string: {key}"
        new_data = self._dict.copy()
        new_data[key] = value
        return Namespace(new_data)

    def with_items(self, items: dict) -> "Namespace":
        """Return a new Namespace with multiple items added."""
        new_data = self._dict.copy()
        for key, value in items.items():
            self._validate_assignment(key)
            assert isinstance(key, str), f"not a string: {key}"
            new_data[key] = value
        return Namespace(new_data)

    # -- static namespace infrastructure --

    #: Namespace which surrounds anything, every namespace should be a superset of this one
    base: "Namespace"

    #: ContextVar tracking the current immutable Namespace
    context: contextvars.ContextVar

    @staticmethod
    def add(key: str, value) -> None:
        """Add an item to the current namespace context."""
        ns = Namespace.context.get()
        Namespace.context.set(ns.with_item(key, value))

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
