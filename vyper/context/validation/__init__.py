from vyper.context.validation.builtins import (  # NOQA:F401
    generate_builtin_namespace,
)
from vyper.context.validation.local import (
    FunctionNodeVisitor,
)
from vyper.context.validation.module import (
    ModuleNodeVisitor,
)


def add_module_namespace(vy_module, interface_codes):
    ModuleNodeVisitor(vy_module, interface_codes)


def validate_functions(vy_module):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        FunctionNodeVisitor(node)
