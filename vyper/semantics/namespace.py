import contextlib

from vyper.ast.identifiers import validate_identifier
from vyper.exceptions import CompilerPanic, NamespaceCollision, UndeclaredDefinition
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions


class Namespace(dict):
    """
    Dictionary subclass that represents the namespace of a contract.

    Attributes
    ----------
    _scopes : List[Set]
        List of sets containing the key names for each scope
    """

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls, *args, **kwargs)
        self._scopes = []
        return self

    def __init__(self):
        super().__init__()
        # NOTE cyclic imports!
        # TODO: break this cycle by providing an `init_vyper_namespace` in 3rd module
        from vyper.builtins.functions import get_builtin_functions
        from vyper.semantics import environment
        from vyper.semantics.analysis.base import VarInfo
        from vyper.semantics.types import PRIMITIVE_TYPES

        self.update(PRIMITIVE_TYPES)
        self.update(environment.get_constant_vars())
        self.update({k: VarInfo(b) for (k, b) in get_builtin_functions().items()})

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

    def clear(self):
        super().clear()
        self.__init__()

    def validate_assignment(self, attr):
        validate_identifier(attr)

        if attr in self:
            prev = super().__getitem__(attr)
            prev_decl = getattr(prev, "decl_node", None)
            msg = f"'{attr}' has already been declared"
            if prev_decl is None:
                msg += f" as a {prev}"
            raise NamespaceCollision(msg, prev_decl=prev_decl)


def get_namespace():
    """
    Get the global namespace object.
    """
    global _namespace
    try:
        return _namespace
    except NameError:
        _namespace = Namespace()
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
