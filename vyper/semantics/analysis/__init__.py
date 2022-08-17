from ..namespace import get_namespace
from .local import validate_functions
from .module import add_module_namespace


def validate_semantics(vyper_ast, interface_codes):
    namespace = get_namespace()

    with namespace.enter_scope():
        add_module_namespace(vyper_ast, interface_codes)
        validate_functions(vyper_ast)
