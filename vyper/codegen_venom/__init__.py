from vyper import ast as vy_ast
from vyper.compiler.settings import Settings
from vyper.semantics.types.module import ModuleT
from vyper.venom.context import IRContext
from vyper.venom.builder import VenomBuilder

from vyper.codegen_venom.context import VenomCodegenContext


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
    # Runtime context
    runtime_ctx = IRContext()
    runtime_fn = runtime_ctx.create_function(MAIN_ENTRY_LABEL)
    runtime_ctx.entry_function = runtime_fn

    runtime_builder = VenomBuilder(runtime_ctx, runtime_fn)
    runtime_codegen_ctx = VenomCodegenContext(module_t, runtime_builder)

    # TODO: Generate selector section, external functions, internal functions
    # For now, emit minimal valid IR
    runtime_builder.stop()

    # Deploy context
    deploy_ctx = IRContext()
    deploy_fn = deploy_ctx.create_function(MAIN_ENTRY_LABEL)
    deploy_ctx.entry_function = deploy_fn

    deploy_builder = VenomBuilder(deploy_ctx, deploy_fn)
    deploy_codegen_ctx = VenomCodegenContext(module_t, deploy_builder)

    # TODO: Generate constructor, deploy code
    # For now, just stop
    deploy_builder.stop()

    return deploy_ctx, runtime_ctx
