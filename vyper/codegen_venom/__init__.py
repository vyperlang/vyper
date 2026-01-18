"""
Direct AST-to-Venom IR code generation.

Bypasses legacy IRnode, generating Venom IR directly from annotated AST.

Public API:
    generate_runtime_venom: Compile contract runtime code
    generate_deploy_venom: Compile contract deployment code

Enable via: vyper --experimental-codegen
"""
from __future__ import annotations

from typing import Optional

from vyper.codegen_venom.module import generate_deploy_venom, generate_runtime_venom
from vyper.compiler.settings import Settings
from vyper.semantics.types.module import ModuleT
from vyper.venom import run_passes_on
from vyper.venom.context import IRContext

MAIN_ENTRY_LABEL = "__main_entry"

# Internal calling convention constants
MAX_STACK_ARGS = 6


def _is_word_type(typ) -> bool:
    """Check if type fits in one stack slot (32 bytes)."""
    return typ.memory_bytes_required == 32


def _returns_word(func_t) -> bool:
    """Check if function returns a single word type."""
    return_t = func_t.return_type
    return return_t is not None and _is_word_type(return_t)


def _pass_via_stack(func_t) -> dict[str, bool]:
    """Determine which args pass via stack vs memory.

    Returns dict mapping arg name -> True if stack, False if memory.
    Word types pass via stack up to MAX_STACK_ARGS.
    """
    ret = {}
    stack_items = 0

    if _returns_word(func_t):
        stack_items += 1

    for arg in func_t.arguments:
        if not _is_word_type(arg.typ) or stack_items > MAX_STACK_ARGS:
            ret[arg.name] = False
        else:
            ret[arg.name] = True
            stack_items += 1

    return ret


def _finalize_venom_ctx(ctx: IRContext, settings: Settings) -> IRContext:
    """Run optimization/normalization passes (required for assembly generation)."""
    # FixMemLocationsPass is the first pass in PASSES_O2/O3/Os
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
    ctx = generate_runtime_venom(module_t, settings)
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
    ctx = generate_deploy_venom(module_t, settings, runtime_bytecode, immutables_len, cbor_metadata)
    return _finalize_venom_ctx(ctx, settings)
