from vyper.context import (
    namespace,
)
from vyper.context.validation.builtins import (
    generate_builtin_namespace,
)
from vyper.context.validation.local import (
    validate_functions,
)
from vyper.context.validation.module import (
    add_module_namespace,
)


def validate_semantics(vyper_ast, interface_codes):
    namespace.clear()
    generate_builtin_namespace()
    add_module_namespace(vyper_ast, interface_codes)
    validate_functions(vyper_ast)
