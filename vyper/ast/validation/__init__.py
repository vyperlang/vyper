from vyper.ast.namespace import get_namespace
from .utils2 import validate_call_args
from .local import validate_functions
from .module import add_module_namespace
from .data_positions import set_data_positions

def validate_semantics(vyper_ast, interface_codes):
    namespace = get_namespace()

    with namespace.enter_scope():
        add_module_namespace(vyper_ast, interface_codes)
        validate_functions(vyper_ast)
