import contextlib
import re

from vyper.exceptions import (
    CompilerPanic,
    NamespaceCollision,
    StructureException,
    UndeclaredDefinition,
)
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions


class Namespace(dict):
    """
    Dictionary subclass that represents the namespace of a contract.

    Attributes
    ----------
    _scopes : List[Set]
        List of sets containing the key names for each scope
    """

    def __init__(self):
        super().__init__()
        self._scopes = []
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
            suggestions_str = get_levenshtein_error_suggestions(key, self, 0.2)
            raise UndeclaredDefinition(f"'{key}' has not been declared. {suggestions_str}")
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
            obj = super().__getitem__(attr)
            raise NamespaceCollision(f"'{attr}' has already been declared as a {obj}")


def get_namespace():
    """
    Get the active namespace object.
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


def validate_identifier(attr):
    if not re.match("^[_a-zA-Z][a-zA-Z0-9_]*$", attr):
        raise StructureException(f"'{attr}' contains invalid character(s)")
    if attr.lower() in RESERVED_KEYWORDS:
        raise StructureException(f"'{attr}' is a reserved keyword")


# https://docs.python.org/3/reference/lexical_analysis.html#keywords
# note we don't technically need to block all python reserved keywords,
# but do it for hygiene
_PYTHON_RESERVED_KEYWORDS = {
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
}
_PYTHON_RESERVED_KEYWORDS = {s.lower() for s in _PYTHON_RESERVED_KEYWORDS}

# Cannot be used for variable or member naming
RESERVED_KEYWORDS = _PYTHON_RESERVED_KEYWORDS | {
    # decorators
    "public",
    "external",
    "nonpayable",
    "constant",
    "immutable",
    "transient",
    "internal",
    "payable",
    "nonreentrant",
    # "class" keywords
    "interface",
    "struct",
    "event",
    "enum",
    # EVM operations
    "unreachable",
    # special functions (no name mangling)
    "init",
    "_init_",
    "___init___",
    "____init____",
    "default",
    "_default_",
    "___default___",
    "____default____",
    # more control flow and special operations
    "range",
    # more special operations
    "indexed",
    # denominations
    "ether",
    "wei",
    "finney",
    "szabo",
    "shannon",
    "lovelace",
    "ada",
    "babbage",
    "gwei",
    "kwei",
    "mwei",
    "twei",
    "pwei",
    # sentinal constant values
    # TODO remove when these are removed from the language
    "zero_address",
    "empty_bytes32",
    "max_int128",
    "min_int128",
    "max_decimal",
    "min_decimal",
    "max_uint256",
    "zero_wei",
}
