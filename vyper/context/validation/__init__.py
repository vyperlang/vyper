from vyper.ast import (
    folding,
)
from vyper.context import (
    namespace,
)
from vyper.context.validation.builtins import (
    add_builtin_namespace,
)
from vyper.context.validation.local import (
    validate_functions,
)
from vyper.context.validation.module import (
    add_module_namespace,
)


def validate_semantics(vyper_ast, interface_codes):
    namespace.clear()
    add_builtin_namespace(vyper_ast)
    folding.fold(vyper_ast, namespace)
    add_module_namespace(vyper_ast, interface_codes)
    folding.fold(vyper_ast, namespace)
    validate_functions(vyper_ast)
