import contextlib

from vyper import ast as vy_ast
from vyper.ast.identifiers import validate_identifier
from vyper.exceptions import CompilerPanic, NamespaceCollision, UndeclaredDefinition
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions


class Namespace(dict):
    """
    Dictionary subclass that represents the namespace of a contract.

    Values must expose a `decl_node` attribute (the AST node the item was
    declared at, or `None` for built-ins); it is used to report the location
    of the previous declaration on a `NamespaceCollision`.

    Attributes
    ----------
    _scopes : List[Set]
        List of sets containing the key names for each scope
    _import_decls : Dict[str, vy_ast.alias]
        Maps (aliased) module names to their import nodes, only used to improve error messages
    """

    _scopes: list[set]
    _import_decls: dict[str, vy_ast.alias]

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls, *args, **kwargs)
        self._scopes = []
        self._import_decls = {}
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
        self.update(environment.CONSTANT_ENVIRONMENT_VARS)
        self.update({k: VarInfo(b) for (k, b) in get_builtin_functions().items()})

    def __eq__(self, other):
        return self is other

    def __setitem__(self, attr, obj):
        if self._scopes:
            self.validate_assignment(attr)
            self._scopes[-1].add(attr)
        assert isinstance(attr, str), f"not a string: {attr}"
        super().__setitem__(attr, obj)

    def set_import(self, attr, obj, alias_node):
        self.__setitem__(attr, obj)
        assert attr not in self._import_decls

        self._import_decls[attr] = alias_node

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
            self._import_decls.pop(key, None)

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

    def copy(self) -> "Namespace":
        """
        Return a copy of this namespace.

        Note: The copy is shallow: the "machinery" is fresh, but the values are shared
        (Even outside Namespace, we try to never copy nodes, so metadata is never stale)
        """

        _ns = Namespace()
        _ns.update(self)
        _ns._scopes = [s.copy() for s in self._scopes]  # 2-deep copy, to keep elements shared
        _ns._import_decls = self._import_decls.copy()
        return _ns

    __copy__ = copy

    def clear(self):
        super().clear()
        self.__init__()

    def validate_assignment(self, attr):
        validate_identifier(attr)

        if attr in self:
            if attr in self._import_decls:
                # point at the alias node rather than the module
                prev_decl = self._import_decls[attr]
            else:
                prev_decl = super().__getitem__(attr).decl_node
            if prev_decl is None:
                msg = f"'{attr}' is already the name of a built-in"
            else:
                msg = f"'{attr}' has already been declared"
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
