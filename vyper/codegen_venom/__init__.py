"""
Direct AST-to-Venom IR code generation.

Bypasses legacy IRnode, generating Venom IR directly from annotated AST.

Public API:
    generate_runtime_venom: Compile contract runtime code
    generate_deploy_venom: Compile contract deployment code

Enable via: vyper --experimental-codegen
"""
from __future__ import annotations

from vyper import ast as vy_ast
from vyper.compiler.settings import Settings
from vyper.semantics.types.module import ModuleT
from vyper.venom import run_passes_on
from vyper.venom.context import IRContext
from vyper.venom.memory_location import fix_mem_loc

from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.module import (
    generate_runtime_venom,
    generate_deploy_venom,
)


MAIN_ENTRY_LABEL = "__main_entry"


def _finalize_venom_ctx(ctx: IRContext, settings: Settings) -> IRContext:
    """Run post-generation fixups and optimization passes."""
    # Fix memory location metadata (required for optimization passes)
    for fn in ctx.functions.values():
        fix_mem_loc(fn)

    # Run optimization/normalization passes (required for assembly generation)
    flags = settings.get_venom_flags()
    run_passes_on(ctx, flags)

    return ctx


def generate_venom_runtime(
    module_t: ModuleT,
    settings: Settings,
) -> IRContext:
    """
    Generate runtime Venom IR directly from annotated AST.

    This is phase 1 of the two-phase compilation. The resulting
    IRContext must be compiled to bytecode before generating
    deploy code.
    """
    ctx = generate_runtime_venom(module_t, settings)
    return _finalize_venom_ctx(ctx, settings)


def generate_venom_deploy(
    module_t: ModuleT,
    settings: Settings,
    runtime_bytecode: bytes,
) -> IRContext:
    """
    Generate deploy Venom IR with embedded runtime bytecode.

    This is phase 2 of the two-phase compilation. The runtime
    bytecode is embedded as a data section and the deploy epilogue
    copies it to memory and returns it.
    """
    immutables_len = module_t.immutable_section_bytes
    ctx = generate_deploy_venom(module_t, settings, runtime_bytecode, immutables_len)
    return _finalize_venom_ctx(ctx, settings)
