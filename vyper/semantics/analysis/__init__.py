from .. import types  # break a dependency cycle.
from ..namespace import get_namespace
from .local import validate_functions
from .module import add_module_namespace
from .utils import _ExprAnalyser


def validate_semantics(vyper_ast, interface_codes):
    # validate semantics and annotate AST with type/semantics information
    namespace = get_namespace()

    with namespace.enter_scope():
        add_module_namespace(vyper_ast, interface_codes)
        validate_functions(vyper_ast)

    # clean up. not sure if this is necessary, but do it for hygiene's sake.
    _ExprAnalyser._reset_taint()
