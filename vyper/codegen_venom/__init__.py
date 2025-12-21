from vyper import ast as vy_ast
from vyper.compiler.settings import Settings
from vyper.semantics.types.module import ModuleT
from vyper.venom.context import IRContext

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.module import generate_ir_for_module, VenomModuleCompiler


MAIN_ENTRY_LABEL = "__main_entry"


def generate_venom_for_module(
    module_ast: vy_ast.Module,
    module_t: ModuleT,
    settings: Settings,
) -> tuple[IRContext, IRContext]:
    """
    Generate Venom IR directly from annotated AST.

    Returns (deploy_ctx, runtime_ctx) - separate IRContexts for
    deployment and runtime code, matching the legacy dual-IR structure.
    """
    return generate_ir_for_module(module_t)
