"""
Direct AST-to-Venom IR code generation.

Bypasses legacy IRnode, generating Venom IR directly from annotated AST.

Public API:
    generate_venom_runtime: Compile contract runtime code
    generate_venom_deploy: Compile contract deployment code

Enable via: vyper --experimental-codegen
"""

from __future__ import annotations

from typing import Optional

from vyper.codegen_venom import module
from vyper.compiler.settings import Settings
from vyper.semantics.types.module import ModuleT
from vyper.venom import run_passes_on
from vyper.venom.context import IRContext


def _finalize_venom_ctx(ctx: IRContext, settings: Settings) -> IRContext:
    """Run optimization/normalization passes (required for assembly generation)."""
    flags = settings.get_venom_flags()
    run_passes_on(ctx, flags)

    return ctx


def generate_venom_runtime(module_t: ModuleT, settings: Settings) -> IRContext:
    """
    Generate runtime Venom IR directly from annotated AST.

    This is phase 1 of the two-phase compilation. The resulting
    IRContext must be compiled to bytecode before generating
    deploy code.
    """
    ctx = module.generate_venom_runtime(module_t, settings)
    return _finalize_venom_ctx(ctx, settings)


def generate_venom_deploy(
    module_t: ModuleT,
    settings: Settings,
    runtime_bytecode: bytes,
    cbor_metadata: Optional[bytes] = None,
) -> IRContext:
    """
    Generate deploy Venom IR with embedded runtime bytecode.

    This is phase 2 of the two-phase compilation. The runtime
    bytecode is embedded as a data section and the deploy epilogue
    copies it to memory and returns it.

    Args:
        module_t: Module type for the contract
        settings: Compiler settings
        runtime_bytecode: Compiled runtime bytecode
        cbor_metadata: Optional CBOR-encoded metadata to append to bytecode
    """
    immutables_len = module_t.immutable_section_bytes
    ctx = module.generate_venom_deploy(
        module_t, settings, runtime_bytecode, immutables_len, cbor_metadata
    )
    return _finalize_venom_ctx(ctx, settings)
