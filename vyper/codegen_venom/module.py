"""
Generate Venom IR for a complete Vyper module.

This module handles:
- Function selector dispatch (linear O(n) strategy)
- External function entry points
- Fallback function handling
- Constructor (deploy) code generation

Two-phase compilation:
1. generate_runtime_venom() - generates runtime code (deployed bytecode)
2. generate_deploy_venom() - generates deploy code with runtime bytecode embedded
"""
from __future__ import annotations

from typing import Optional

import vyper.ast as vy_ast
from vyper.codegen import jumptable_utils
from vyper.codegen.function_definitions.common import EntryPointInfo, _FuncIRInfo
from vyper.codegen_venom.abi.abi_decoder import _getelemptr_abi, abi_decode_to_buf
from vyper.codegen_venom.buffer import Ptr
from vyper.codegen_venom.constants import SELECTOR_BYTES, SELECTOR_SHIFT_BITS
from vyper.codegen_venom.value import VyperValue
from vyper.compiler.settings import Settings, _opt_codesize, _opt_none
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import TupleT, VyperType
from vyper.semantics.types.function import ContractFunctionT, StateMutability
from vyper.semantics.types.module import ModuleT
from vyper.utils import OrderedSet, method_id_int
from vyper.venom.basicblock import IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext
from vyper.venom.memory_location import Allocation

from .context import Constancy, VenomCodegenContext
from .expr import Expr
from .stmt import Stmt


def _get_constancy(func_t: ContractFunctionT) -> Constancy:
    """Get constancy based on function mutability."""
    if func_t.mutability in (StateMutability.VIEW, StateMutability.PURE):
        return Constancy.Constant
    return Constancy.Mutable


class IDGenerator:
    """Assign unique IDs to functions."""

    def __init__(self):
        self._id = 0

    def ensure_id(self, fn_t: ContractFunctionT) -> None:
        if fn_t._function_id is None:
            fn_t._function_id = self._id
            self._id += 1


def _is_constructor(func_ast) -> bool:
    return func_ast._metadata["func_type"].is_constructor


def _is_fallback(func_ast) -> bool:
    return func_ast._metadata["func_type"].is_fallback


def _is_internal(func_ast) -> bool:
    return func_ast._metadata["func_type"].is_internal


def _runtime_reachable_functions(module_t: ModuleT, id_generator: IDGenerator):
    """Calculate globally reachable functions for runtime code."""
    ret: OrderedSet[ContractFunctionT] = OrderedSet()

    for fn_t in module_t.exposed_functions:
        assert isinstance(fn_t.ast_def, vy_ast.FunctionDef)
        ret.update(fn_t.reachable_internal_functions)
        ret.add(fn_t)

    for fn_t in ret:
        id_generator.ensure_id(fn_t)

    return ret


def _init_ir_info(func_t: ContractFunctionT) -> None:
    """Initialize IRInfo on a function if not already set."""
    if func_t._ir_info is None:
        func_t._ir_info = _FuncIRInfo(func_t)


# =============================================================================
# Public API: Two-phase compilation
# =============================================================================


def generate_runtime_venom(module_t: ModuleT, settings: Settings) -> IRContext:
    """
    Generate runtime Venom IR directly from annotated AST.

    This is phase 1 of the two-phase compilation. The resulting
    IRContext must be compiled to bytecode before generating
    deploy code.
    """
    id_generator = IDGenerator()

    # Find all reachable functions
    reachable = _runtime_reachable_functions(module_t, id_generator)
    function_defs = [fn_t.ast_def for fn_t in reachable]

    runtime_functions = [f for f in function_defs if not _is_constructor(f)]
    internal_functions = [f for f in runtime_functions if _is_internal(f)]
    external_functions = [
        f for f in runtime_functions if not _is_internal(f) and not _is_fallback(f)
    ]
    default_function = next((f for f in runtime_functions if _is_fallback(f)), None)

    # Create runtime IR context
    runtime_ctx = IRContext()
    runtime_fn = runtime_ctx.create_function("runtime")
    runtime_ctx.entry_function = runtime_fn  # Mark as entry point
    runtime_builder = VenomBuilder(runtime_ctx, runtime_fn)

    # Generate selector dispatch
    # Selection logic matches legacy codegen:
    # - opt_none: linear search (O(n))
    # - opt_codesize with >4 functions: dense jumptable (O(1), codesize-optimized)
    # - >3 functions: sparse jumptable (O(1) average, gas-optimized)
    # - otherwise: linear search
    if _opt_none():
        _generate_selector_section_linear(
            runtime_builder, module_t, external_functions, default_function
        )
    elif _opt_codesize() and len(external_functions) > 4:
        _generate_selector_section_dense(
            runtime_builder, module_t, external_functions, default_function
        )
    elif len(external_functions) > 3:
        _generate_selector_section_sparse(
            runtime_builder, module_t, external_functions, default_function
        )
    else:
        _generate_selector_section_linear(
            runtime_builder, module_t, external_functions, default_function
        )

    # Generate internal functions for runtime
    for func_ast in internal_functions:
        _generate_internal_function(runtime_ctx, module_t, func_ast, is_ctor_context=False)

    return runtime_ctx


def generate_deploy_venom(
    module_t: ModuleT,
    settings: Settings,
    runtime_bytecode: bytes,
    immutables_len: int,
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
        immutables_len: Size of immutables section in bytes
        cbor_metadata: Optional CBOR-encoded metadata to append to bytecode
    """
    id_generator = IDGenerator()

    # Create deploy IR context
    deploy_ctx = IRContext()

    # Add runtime bytecode as data section
    deploy_ctx.append_data_section(IRLabel("runtime_begin"))
    deploy_ctx.append_data_item(runtime_bytecode)

    # Add CBOR metadata if provided
    if cbor_metadata is not None:
        deploy_ctx.append_data_section(IRLabel("cbor_metadata"))
        deploy_ctx.append_data_item(cbor_metadata)

    deploy_fn = deploy_ctx.create_function("deploy")
    deploy_ctx.entry_function = deploy_fn  # Mark as entry point
    deploy_builder = VenomBuilder(deploy_ctx, deploy_fn)

    init_func_t = module_t.init_function

    if init_func_t is not None:
        id_generator.ensure_id(init_func_t)

        # Assign IDs to reachable internal functions from constructor
        for func_t in init_func_t.reachable_internal_functions:
            id_generator.ensure_id(func_t)

        # Create shared alloca_id for immutables region
        # This ensures all ctor-context functions use the same memory region
        immutables_alloca_id = deploy_ctx.get_next_alloca_id() if immutables_len > 0 else None

        # Generate constructor
        assert isinstance(init_func_t.ast_def, vy_ast.FunctionDef)
        _generate_constructor(
            deploy_builder,
            module_t,
            init_func_t.ast_def,
            len(runtime_bytecode),
            immutables_len,
            immutables_alloca_id,
        )

        # Generate internal functions reachable from constructor
        for func_t in init_func_t.reachable_internal_functions:
            _generate_internal_function(
                deploy_ctx,
                module_t,
                func_t.ast_def,
                is_ctor_context=True,
                immutables_len=immutables_len,
                immutables_alloca_id=immutables_alloca_id,
            )
    else:
        # No constructor - just deploy runtime
        _generate_simple_deploy(deploy_builder, len(runtime_bytecode), immutables_len)

    return deploy_ctx


# =============================================================================
# Module-level helper functions (refactored from VenomModuleCompiler)
# =============================================================================


def _generate_selector_section_linear(
    builder: VenomBuilder,
    module_t: ModuleT,
    external_functions: list,
    default_function: Optional[vy_ast.FunctionDef],
) -> None:
    """Generate O(n) linear selector dispatch.

    Structure:
    - Check calldatasize >= 4
    - Load method_id from calldata
    - For each function: if method_id matches, goto entry point
    - Fallback to default function or revert

    For functions with kwargs, generates ONE shared common body with
    separate entry points that handle kwargs and jump to the common body.
    """
    # Check calldatasize >= SELECTOR_BYTES (4 bytes)
    calldatasize = builder.calldatasize()
    has_selector = builder.iszero(builder.lt(calldatasize, IRLiteral(SELECTOR_BYTES)))

    dispatch_bb = builder.create_block("dispatch")
    fallback_bb = builder.create_block("fallback")

    # If calldatasize < 4, goto fallback
    builder.jnz(has_selector, dispatch_bb.label, fallback_bb.label)

    # Dispatch block: load selector and check functions
    builder.append_block(dispatch_bb)
    builder.set_block(dispatch_bb)

    # _calldata_method_id = shr(SELECTOR_SHIFT_BITS, calldataload(0))
    raw_selector = builder.calldataload(IRLiteral(0))
    method_id = builder.shr(IRLiteral(SELECTOR_SHIFT_BITS), raw_selector)

    # Collect deferred common bodies to generate after all dispatch checks
    deferred_common_bodies: list[tuple[vy_ast.FunctionDef, ContractFunctionT, IRLabel]] = []

    # Generate entry points and dispatch checks
    for func_ast in external_functions:
        func_t = func_ast._metadata["func_type"]
        _init_ir_info(func_t)

        # Generate entry points for all ABI signatures (kwargs create multiple)
        entry_points = _generate_external_entry_points(func_t)

        has_kwargs = len(func_t.keyword_args) > 0
        common_label = None

        if has_kwargs:
            # Create allocas for kwargs BEFORE entry points (so allocas dominate uses)
            _create_kwarg_allocas(builder, func_t)
            # Create label for common body block
            common_label = IRLabel(f"fn_{func_t._function_id}_common")
            deferred_common_bodies.append((func_ast, func_t, common_label))

        for abi_sig, entry_info in entry_points.items():
            method_id_val = method_id_int(abi_sig)

            # Create block for this function's dispatch
            match_bb = builder.create_block(f"match_{method_id_val:08x}")

            # Check if method_id matches
            is_match = builder.eq(method_id, IRLiteral(method_id_val))

            # Create next check block
            next_check_bb = builder.create_block("next_check")

            builder.jnz(is_match, match_bb.label, next_check_bb.label)

            # Match block: payable/calldatasize checks, then kwargs or body
            builder.append_block(match_bb)
            builder.set_block(match_bb)

            _emit_entry_checks(builder, func_t, entry_info.min_calldatasize)

            if has_kwargs:
                # Entry point: handle kwargs, jump to common body
                assert common_label is not None
                _generate_entry_point_kwargs(builder, module_t, func_t, entry_info, common_label)
            else:
                # No kwargs: generate body directly
                _generate_external_function_body(builder, module_t, func_t, func_ast, entry_info)

            # Continue checking other functions
            builder.append_block(next_check_bb)
            builder.set_block(next_check_bb)

    # No match found - goto fallback
    builder.jmp(fallback_bb.label)

    # Generate deferred common bodies for functions with kwargs
    for func_ast, func_t, common_label in deferred_common_bodies:
        common_bb = builder.create_block(common_label.value)
        common_bb.label = common_label
        builder.append_block(common_bb)
        builder.set_block(common_bb)
        _generate_common_function_body(builder, module_t, func_t, func_ast)

    # Fallback block
    builder.append_block(fallback_bb)
    builder.set_block(fallback_bb)

    if default_function:
        func_t = default_function._metadata["func_type"]
        _init_ir_info(func_t)

        # Payable check for fallback
        if not func_t.is_payable:
            callvalue = builder.callvalue()
            is_zero = builder.iszero(callvalue)
            builder.assert_(is_zero)

        # Generate fallback body
        _generate_fallback_body(builder, module_t, func_t, default_function)
    else:
        # No fallback - revert
        builder.revert(IRLiteral(0), IRLiteral(0))


def _generate_selector_section_sparse(
    builder: VenomBuilder,
    module_t: ModuleT,
    external_functions: list,
    default_function: Optional[vy_ast.FunctionDef],
) -> None:
    """Generate O(1) average-case sparse jumptable selector dispatch.

    Structure:
    - Check calldatasize >= 4
    - Load method_id from calldata
    - Compute bucket_id = method_id % n_buckets
    - Load bucket location from data section header
    - djmp to bucket's label
    - Each bucket does linear search through its items (typically 1-3)
    - Falls through to fallback on no match

    For functions with kwargs, generates ONE shared common body with
    separate entry points that handle kwargs and jump to the common body.
    """
    runtime_ctx = builder.ctx

    # Check calldatasize >= SELECTOR_BYTES (4 bytes)
    calldatasize = builder.calldatasize()
    has_selector = builder.iszero(builder.lt(calldatasize, IRLiteral(SELECTOR_BYTES)))

    dispatch_bb = builder.create_block("dispatch")
    fallback_bb = builder.create_block("fallback")

    # If calldatasize < 4, goto fallback
    builder.jnz(has_selector, dispatch_bb.label, fallback_bb.label)

    # Dispatch block: load selector and dispatch to bucket
    builder.append_block(dispatch_bb)
    builder.set_block(dispatch_bb)

    # _calldata_method_id = shr(SELECTOR_SHIFT_BITS, calldataload(0))
    raw_selector = builder.calldataload(IRLiteral(0))
    method_id = builder.shr(IRLiteral(SELECTOR_SHIFT_BITS), raw_selector)

    # Collect all entry points and track common body labels for kwargs functions
    all_entry_points: dict[str, tuple[vy_ast.FunctionDef, EntryPointInfo]] = {}
    common_labels: dict[int, IRLabel] = {}  # func_id -> common label
    deferred_common_bodies: list[tuple[vy_ast.FunctionDef, ContractFunctionT, IRLabel]] = []

    for func_ast in external_functions:
        func_t = func_ast._metadata["func_type"]
        _init_ir_info(func_t)
        entry_points = _generate_external_entry_points(func_t)

        # Track common label for functions with kwargs
        if len(func_t.keyword_args) > 0:
            # Create allocas for kwargs BEFORE entry points (so allocas dominate uses)
            _create_kwarg_allocas(builder, func_t)
            common_label = IRLabel(f"fn_{func_t._function_id}_common")
            common_labels[func_t._function_id] = common_label
            deferred_common_bodies.append((func_ast, func_t, common_label))

        for abi_sig, entry_info in entry_points.items():
            all_entry_points[abi_sig] = (func_ast, entry_info)

    if not all_entry_points:
        # No external functions - jump to fallback
        builder.jmp(fallback_bb.label)
    else:
        # Generate buckets
        n_buckets, buckets = jumptable_utils.generate_sparse_jumptable_buckets(
            all_entry_points.keys()
        )

        SZ_BUCKET_HEADER = 2  # 2 bytes for bucket location

        if n_buckets > 1:
            # Compute bucket_id = method_id % n_buckets
            bucket_id = builder.mod(method_id, IRLiteral(n_buckets))

            # Create data section with bucket headers
            runtime_ctx.append_data_section(IRLabel("selector_buckets", is_symbol=True))

            # Build jump targets list and add bucket header labels
            jump_targets = []
            for i in range(n_buckets):
                if i in buckets:
                    bucket_label = IRLabel(f"selector_bucket_{i}", is_symbol=True)
                    jump_targets.append(bucket_label)
                else:
                    # Empty bucket -> fallback
                    jump_targets.append(fallback_bb.label)
                runtime_ctx.append_data_item(jump_targets[-1])

            # Load bucket location from data header
            # Location = selector_buckets + bucket_id * 2
            bucket_hdr_offset = builder.mul(bucket_id, IRLiteral(SZ_BUCKET_HEADER))
            # Use add with label - the label resolves to its code position at link time
            selector_buckets_addr = builder.offset(
                IRLiteral(0), IRLabel("selector_buckets", is_symbol=True)
            )
            bucket_hdr_location = builder.add(selector_buckets_addr, bucket_hdr_offset)

            # Copy 2-byte header to memory at offset (32 - 2) = 30
            # so mload(0) reads it right-aligned in a 32-byte word
            dst = 32 - SZ_BUCKET_HEADER
            builder.codecopy(IRLiteral(dst), bucket_hdr_location, IRLiteral(SZ_BUCKET_HEADER))
            jumpdest = builder.mload(IRLiteral(0))

            # Dynamic jump to bucket (must list all possible targets)
            builder.djmp(jumpdest, *jump_targets)

            # Generate bucket blocks
            for bucket_id_val, bucket_method_ids in buckets.items():
                bucket_label = IRLabel(f"selector_bucket_{bucket_id_val}", is_symbol=True)
                bucket_bb = builder.create_block(f"bucket_{bucket_id_val}")
                # Override the label to match the data section reference
                bucket_bb.label = bucket_label
                builder.append_block(bucket_bb)
                builder.set_block(bucket_bb)

                # Linear search through bucket's method_ids
                for mid in bucket_method_ids:
                    # Find the abi_sig for this method_id
                    for abi_sig, (func_ast, entry_info) in all_entry_points.items():
                        if method_id_int(abi_sig) == mid:
                            func_t = entry_info.func_t
                            has_kwargs = len(func_t.keyword_args) > 0

                            # Create match block for this function
                            match_bb = builder.create_block(f"match_{mid:08x}")

                            # Check if method_id matches
                            is_match = builder.eq(method_id, IRLiteral(mid))

                            # Handle trailing zeros in method_id
                            # If method_id ends with \x00, we need calldatasize check
                            # to distinguish from truncated calldata
                            has_trailing_zeroes = mid.to_bytes(4, "big").endswith(b"\x00")
                            if has_trailing_zeroes:
                                has_enough_calldata = builder.iszero(
                                    builder.lt(builder.calldatasize(), IRLiteral(4))
                                )
                                is_match = builder.and_(has_enough_calldata, is_match)

                            # Create next check block
                            next_check_bb = builder.create_block("next_check")

                            builder.jnz(is_match, match_bb.label, next_check_bb.label)

                            # Match block: payable/calldatasize checks, then kwargs or body
                            builder.append_block(match_bb)
                            builder.set_block(match_bb)

                            _emit_entry_checks(builder, func_t, entry_info.min_calldatasize)

                            if has_kwargs:
                                # Entry point: handle kwargs, jump to common body
                                assert func_t._function_id is not None  # help mypy
                                common_label = common_labels[func_t._function_id]
                                _generate_entry_point_kwargs(
                                    builder, module_t, func_t, entry_info, common_label
                                )
                            else:
                                # No kwargs: generate body directly
                                _generate_external_function_body(
                                    builder, module_t, func_t, func_ast, entry_info
                                )

                            # Continue with next check
                            builder.append_block(next_check_bb)
                            builder.set_block(next_check_bb)
                            break

                # No match in this bucket - goto fallback
                builder.jmp(fallback_bb.label)

        else:
            # Only one bucket - do linear search without jumptable overhead
            for abi_sig, (func_ast, entry_info) in all_entry_points.items():
                method_id_val = method_id_int(abi_sig)
                func_t = entry_info.func_t
                has_kwargs = len(func_t.keyword_args) > 0

                match_bb = builder.create_block(f"match_{method_id_val:08x}")
                is_match = builder.eq(method_id, IRLiteral(method_id_val))
                next_check_bb = builder.create_block("next_check")

                builder.jnz(is_match, match_bb.label, next_check_bb.label)

                builder.append_block(match_bb)
                builder.set_block(match_bb)

                _emit_entry_checks(builder, func_t, entry_info.min_calldatasize)

                if has_kwargs:
                    assert func_t._function_id is not None  # help mypy
                    common_label = common_labels[func_t._function_id]
                    _generate_entry_point_kwargs(
                        builder, module_t, func_t, entry_info, common_label
                    )
                else:
                    _generate_external_function_body(
                        builder, module_t, func_t, func_ast, entry_info
                    )

                builder.append_block(next_check_bb)
                builder.set_block(next_check_bb)

            # No match - goto fallback
            builder.jmp(fallback_bb.label)

    # Generate deferred common bodies for functions with kwargs
    for func_ast, func_t, common_label in deferred_common_bodies:
        common_bb = builder.create_block(common_label.value)
        common_bb.label = common_label
        builder.append_block(common_bb)
        builder.set_block(common_bb)
        _generate_common_function_body(builder, module_t, func_t, func_ast)

    # Fallback block
    builder.append_block(fallback_bb)
    builder.set_block(fallback_bb)

    if default_function:
        func_t = default_function._metadata["func_type"]
        _init_ir_info(func_t)

        # Payable check for fallback
        if not func_t.is_payable:
            callvalue = builder.callvalue()
            is_zero = builder.iszero(callvalue)
            builder.assert_(is_zero)

        # Generate fallback body
        _generate_fallback_body(builder, module_t, func_t, default_function)
    else:
        # No fallback - revert
        builder.revert(IRLiteral(0), IRLiteral(0))


def _generate_selector_section_dense(
    builder: VenomBuilder,
    module_t: ModuleT,
    external_functions: list,
    default_function: Optional[vy_ast.FunctionDef],
) -> None:
    """Generate O(1) dense jumptable selector dispatch.

    Uses two-level perfect hash for guaranteed O(1) lookup. Optimized for codesize.

    Structure:
    - Check calldatasize >= 4
    - Load method_id from calldata
    - Compute bucket_id = method_id % n_buckets
    - Load bucket header (magic, location, size)
    - Compute func_id = ((method_id * bucket_magic) >> BITS_MAGIC) % bucket_size
    - Load function info (method_id, label, metadata)
    - Verify method_id matches and check entry conditions
    - Jump to function label

    Data layout:
    - BUCKET_HEADERS: 5 bytes each (magic 2b | location 2b | size 1b)
    - Per-bucket function info: 7+ bytes each (method_id 4b | label 2b | metadata 1-3b)

    For functions with kwargs, generates ONE shared common body with
    separate entry points that handle kwargs and jump to the common body.
    """
    runtime_ctx = builder.ctx

    # Check calldatasize >= SELECTOR_BYTES (4 bytes)
    calldatasize = builder.calldatasize()
    has_selector = builder.iszero(builder.lt(calldatasize, IRLiteral(SELECTOR_BYTES)))

    dispatch_bb = builder.create_block("dispatch")
    fallback_bb = builder.create_block("fallback")

    # If calldatasize < 4, goto fallback
    builder.jnz(has_selector, dispatch_bb.label, fallback_bb.label)

    # Dispatch block: load selector and dispatch via dense jumptable
    builder.append_block(dispatch_bb)
    builder.set_block(dispatch_bb)

    # _calldata_method_id = shr(SELECTOR_SHIFT_BITS, calldataload(0))
    raw_selector = builder.calldataload(IRLiteral(0))
    method_id = builder.shr(IRLiteral(SELECTOR_SHIFT_BITS), raw_selector)

    # Collect all entry points and track common body labels for kwargs functions
    all_entry_points: dict[str, tuple[vy_ast.FunctionDef, EntryPointInfo]] = {}
    common_labels: dict[int, IRLabel] = {}  # func_id -> common label
    deferred_common_bodies: list[tuple[vy_ast.FunctionDef, ContractFunctionT, IRLabel]] = []

    for func_ast in external_functions:
        func_t = func_ast._metadata["func_type"]
        _init_ir_info(func_t)
        entry_points = _generate_external_entry_points(func_t)

        # Track common label for functions with kwargs
        if len(func_t.keyword_args) > 0:
            # Create allocas for kwargs BEFORE entry points (so allocas dominate uses)
            _create_kwarg_allocas(builder, func_t)
            common_label = IRLabel(f"fn_{func_t._function_id}_common")
            common_labels[func_t._function_id] = common_label
            deferred_common_bodies.append((func_ast, func_t, common_label))

        for abi_sig, entry_info in entry_points.items():
            all_entry_points[abi_sig] = (func_ast, entry_info)

    if not all_entry_points:
        # No external functions - jump to fallback
        builder.jmp(fallback_bb.label)
    else:
        # Generate dense jumptable info
        n_buckets, jumptable_info = jumptable_utils.generate_dense_jumptable_info(
            all_entry_points.keys()
        )

        # Sanity check bucket IDs
        assert n_buckets == len(jumptable_info)
        for i, (bucket_id, _) in enumerate(sorted(jumptable_info.items())):
            assert i == bucket_id

        # Bucket header: magic <2 bytes> | location <2 bytes> | size <1 byte>
        SZ_BUCKET_HEADER = 5

        # Figure out the minimum number of bytes to encode min_calldatasize in function info
        largest_mincalldatasize = max(
            entry_info.min_calldatasize for _, entry_info in all_entry_points.values()
        )
        FN_METADATA_BYTES = (largest_mincalldatasize.bit_length() + 7) // 8

        # Function info size: method_id <4 bytes> | label <2 bytes> | metadata <1-3 bytes>
        func_info_size = 4 + 2 + FN_METADATA_BYTES

        # Create labels for each entry point (for djmp targets)
        entry_point_labels: dict[str, IRLabel] = {}
        for abi_sig, (_func_ast, _entry_info) in all_entry_points.items():
            method_id_val = method_id_int(abi_sig)
            label = IRLabel(f"entry_{method_id_val:08x}", is_symbol=True)
            entry_point_labels[abi_sig] = label

        # Compute bucket_id = method_id % n_buckets
        bucket_id_var = builder.mod(method_id, IRLiteral(n_buckets))

        # Create data section for bucket headers
        runtime_ctx.append_data_section(IRLabel("BUCKET_HEADERS", is_symbol=True))
        for bucket_id_val, bucket in sorted(jumptable_info.items()):
            runtime_ctx.append_data_item(bucket.magic.to_bytes(2, "big"))
            runtime_ctx.append_data_item(IRLabel(f"bucket_{bucket_id_val}", is_symbol=True))
            runtime_ctx.append_data_item(bucket.bucket_size.to_bytes(1, "big"))

        # Load bucket header from data section
        # Location = BUCKET_HEADERS + bucket_id * 5
        bucket_hdr_offset = builder.mul(bucket_id_var, IRLiteral(SZ_BUCKET_HEADER))
        bucket_headers_addr = builder.offset(
            IRLiteral(0), IRLabel("BUCKET_HEADERS", is_symbol=True)
        )
        bucket_hdr_location = builder.add(bucket_headers_addr, bucket_hdr_offset)

        # Copy 5-byte header to memory at offset (32 - 5) = 27
        # so mload(0) reads it right-aligned in a 32-byte word
        dst = 32 - SZ_BUCKET_HEADER
        builder.codecopy(IRLiteral(dst), bucket_hdr_location, IRLiteral(SZ_BUCKET_HEADER))
        hdr_info = builder.mload(IRLiteral(0))

        # Extract bucket header fields:
        # hdr_info layout (right-aligned in 32 bytes):
        #   [unused...] [magic:2] [location:2] [size:1]
        # After mload(0), the 5 bytes are in the low 40 bits
        bucket_location = builder.and_(IRLiteral(0xFFFF), builder.shr(IRLiteral(8), hdr_info))
        bucket_magic = builder.shr(IRLiteral(24), hdr_info)
        bucket_size = builder.and_(IRLiteral(0xFF), hdr_info)

        # Compute func_id = ((method_id * bucket_magic) >> BITS_MAGIC) % bucket_size
        magic_product = builder.mul(bucket_magic, method_id)
        shifted = builder.shr(IRLiteral(jumptable_utils.BITS_MAGIC), magic_product)
        func_id = builder.mod(shifted, bucket_size)

        # Load function info from bucket
        # Location = bucket_location + func_id * func_info_size
        func_info_offset = builder.mul(func_id, IRLiteral(func_info_size))
        func_info_location = builder.add(bucket_location, func_info_offset)

        # Copy function info to memory
        dst = 32 - func_info_size
        assert func_info_size >= SZ_BUCKET_HEADER  # otherwise mload will have dirty bytes
        builder.codecopy(IRLiteral(dst), func_info_location, IRLiteral(func_info_size))
        func_info = builder.mload(IRLiteral(0))

        # Extract function info fields:
        # func_info layout (right-aligned):
        #   [method_id:4] [label:2] [metadata:FN_METADATA_BYTES]
        fn_metadata_mask = 2 ** (FN_METADATA_BYTES * 8) - 1
        calldatasize_mask = fn_metadata_mask - 1  # ex. 0xFFFE (low bit is nonpayable flag)

        is_nonpayable = builder.and_(IRLiteral(1), func_info)
        expected_calldatasize = builder.and_(IRLiteral(calldatasize_mask), func_info)

        label_bits_ofst = FN_METADATA_BYTES * 8
        function_label = builder.and_(
            IRLiteral(0xFFFF), builder.shr(IRLiteral(label_bits_ofst), func_info)
        )
        method_id_bits_ofst = (FN_METADATA_BYTES + 2) * 8
        function_method_id = builder.shr(IRLiteral(method_id_bits_ofst), func_info)

        # Check method_id is correct (handles trailing zeros case)
        calldatasize_valid = builder.gt(builder.calldatasize(), IRLiteral(3))
        method_id_correct = builder.eq(function_method_id, method_id)
        should_continue = builder.and_(calldatasize_valid, method_id_correct)
        should_fallback = builder.iszero(should_continue)

        # If method_id doesn't match, goto fallback
        check_passed_bb = builder.create_block("check_passed")
        builder.jnz(should_fallback, fallback_bb.label, check_passed_bb.label)

        builder.append_block(check_passed_bb)
        builder.set_block(check_passed_bb)

        # Assert callvalue == 0 if nonpayable
        bad_callvalue = builder.mul(is_nonpayable, builder.callvalue())
        # Assert calldatasize >= expected
        bad_calldatasize = builder.lt(builder.calldatasize(), expected_calldatasize)
        failed_entry_conditions = builder.or_(bad_callvalue, bad_calldatasize)
        builder.assert_(builder.iszero(failed_entry_conditions))

        # Dynamic jump to function label
        jump_targets = list(entry_point_labels.values())
        builder.djmp(function_label, *jump_targets)

        # Create data sections for each bucket's function info
        for bucket_id_val, bucket in jumptable_info.items():
            runtime_ctx.append_data_section(IRLabel(f"bucket_{bucket_id_val}", is_symbol=True))

            # Sort function infos by their image (hash position)
            for mid in bucket.method_ids_image_order:
                # Find the matching_sig for this method_id
                matching_sig: Optional[str] = None
                for sig in all_entry_points.keys():
                    if method_id_int(sig) == mid:
                        matching_sig = sig
                        break
                assert matching_sig is not None

                _, entry_info = all_entry_points[matching_sig]

                # method_id <4 bytes>
                runtime_ctx.append_data_item(mid.to_bytes(4, "big"))
                # label <2 bytes> (symbol reference)
                runtime_ctx.append_data_item(entry_point_labels[matching_sig])
                # metadata: min_calldatasize | is_nonpayable (packed)
                func_metadata_int = entry_info.min_calldatasize | int(
                    not entry_info.func_t.is_payable
                )
                runtime_ctx.append_data_item(func_metadata_int.to_bytes(FN_METADATA_BYTES, "big"))

        # Generate entry point blocks for each function
        for abi_sig, (func_ast, entry_info) in all_entry_points.items():
            label = entry_point_labels[abi_sig]
            func_t = entry_info.func_t
            has_kwargs = len(func_t.keyword_args) > 0

            entry_bb = builder.create_block(f"entry_{method_id_int(abi_sig):08x}")
            entry_bb.label = label
            builder.append_block(entry_bb)
            builder.set_block(entry_bb)

            if has_kwargs:
                # Entry point: handle kwargs, jump to common body
                assert func_t._function_id is not None  # help mypy
                common_label = common_labels[func_t._function_id]
                _generate_entry_point_kwargs(builder, module_t, func_t, entry_info, common_label)
            else:
                # No kwargs: generate body directly (entry checks already done in dispatcher)
                _generate_external_function_body(builder, module_t, func_t, func_ast, entry_info)

    # Generate deferred common bodies for functions with kwargs
    for func_ast, func_t, common_label in deferred_common_bodies:
        common_bb = builder.create_block(common_label.value)
        common_bb.label = common_label
        builder.append_block(common_bb)
        builder.set_block(common_bb)
        _generate_common_function_body(builder, module_t, func_t, func_ast)

    # Fallback block
    builder.append_block(fallback_bb)
    builder.set_block(fallback_bb)

    if default_function:
        func_t = default_function._metadata["func_type"]
        _init_ir_info(func_t)

        # Payable check for fallback
        if not func_t.is_payable:
            callvalue = builder.callvalue()
            is_zero = builder.iszero(callvalue)
            builder.assert_(is_zero)

        # Generate fallback body
        _generate_fallback_body(builder, module_t, func_t, default_function)
    else:
        # No fallback - revert
        builder.revert(IRLiteral(0), IRLiteral(0))


def _emit_entry_checks(
    builder: VenomBuilder, func_t: ContractFunctionT, min_calldatasize: int
) -> None:
    """Emit payable and calldatasize checks for external function entry."""
    # Payable check
    if not func_t.is_payable:
        callvalue = builder.callvalue()
        is_zero = builder.iszero(callvalue)
        builder.assert_(is_zero)

    # Calldatasize check
    if min_calldatasize > SELECTOR_BYTES:
        calldatasize = builder.calldatasize()
        is_enough = builder.iszero(builder.lt(calldatasize, IRLiteral(min_calldatasize)))
        builder.assert_(is_enough)


def _generate_external_entry_points(func_t: ContractFunctionT) -> dict[str, EntryPointInfo]:
    """Generate entry point info for each ABI signature.

    Functions with kwargs have multiple entry points:
    - f(a, b) with c=1, d=2 defaults creates:
      - f(a, b): fills c and d from defaults
      - f(a, b, c): fills d from default
      - f(a, b, c, d): no defaults
    """
    entry_points = {}

    positional_args = func_t.positional_args
    keyword_args = func_t.keyword_args

    # Generate entry point for each kwarg combination
    for i in range(len(keyword_args) + 1):
        calldata_kwargs = keyword_args[:i]

        calldata_args = positional_args + calldata_kwargs
        calldata_args_t = TupleT(tuple(arg.typ for arg in calldata_args))

        abi_sig = func_t.abi_signature_for_kwargs(calldata_kwargs)
        min_calldatasize = SELECTOR_BYTES + calldata_args_t.abi_type.static_size()

        entry_points[abi_sig] = EntryPointInfo(
            func_t=func_t,
            min_calldatasize=min_calldatasize,
            ir_node=None,  # We generate IR directly, not via IRnode
        )

    return entry_points


def _generate_external_function_body(
    builder: VenomBuilder,
    module_t: ModuleT,
    func_t: ContractFunctionT,
    func_ast: vy_ast.FunctionDef,
    entry_info: EntryPointInfo,
) -> None:
    """Generate the body of an external function.

    This includes:
    1. Register/decode base args from calldata
    2. Handle kwargs (copy from calldata or use defaults)
    3. Nonreentrant lock
    4. Function body
    5. Exit sequence with return encoding
    """
    # Create codegen context for this function
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        constancy=_get_constancy(func_t),
        is_ctor_context=False,
    )

    # Register positional args from calldata
    _register_positional_args(codegen_ctx, func_t)

    # Handle kwargs (allocate memory, copy from calldata or defaults)
    _handle_kwargs(codegen_ctx, func_t, entry_info)

    # Nonreentrant lock
    codegen_ctx.emit_nonreentrant_lock(func_t)

    # Function body
    for stmt in func_ast.body:
        Stmt(stmt, codegen_ctx).lower()

    # If no explicit return, add stop/return
    if not builder.is_terminated():
        codegen_ctx.emit_nonreentrant_unlock(func_t)
        if func_t.return_type is None:
            builder.stop()
        else:
            # This shouldn't happen - function should have return stmt
            raise CompilerPanic("External function missing return")


def _generate_entry_point_kwargs(
    builder: VenomBuilder,
    module_t: ModuleT,
    func_t: ContractFunctionT,
    entry_info: EntryPointInfo,
    common_label: IRLabel,
) -> None:
    """Generate entry point code that handles kwargs and jumps to common body.

    This is called for functions with kwargs. Each entry point:
    1. Writes kwargs to pre-allocated alloca locations (defaults or from calldata)
    2. Jumps to the common body label

    The allocas must have been created earlier via _create_kwarg_allocas.
    """
    # Create codegen context for kwarg handling only
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        constancy=_get_constancy(func_t),
        is_ctor_context=False,
    )

    # Handle kwargs - write to pre-allocated allocas
    _init_kwargs_in_entry_point(codegen_ctx, func_t, entry_info)

    # Jump to common body
    builder.jmp(common_label)


def _generate_common_function_body(
    builder: VenomBuilder,
    module_t: ModuleT,
    func_t: ContractFunctionT,
    func_ast: vy_ast.FunctionDef,
) -> None:
    """Generate the common body of an external function with kwargs.

    This is the shared code that all entry points jump to after handling kwargs.
    It includes:
    1. Register/decode base args from calldata
    2. Register pre-allocated kwargs (already in memory)
    3. Nonreentrant lock
    4. Function body
    5. Exit sequence with return encoding
    """
    # Create codegen context for this function
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        constancy=_get_constancy(func_t),
        is_ctor_context=False,
    )

    # Register positional args from calldata
    _register_positional_args(codegen_ctx, func_t)

    # Register pre-allocated kwargs (just register the existing allocas)
    _register_kwarg_variables(codegen_ctx, func_t)

    # Nonreentrant lock
    codegen_ctx.emit_nonreentrant_lock(func_t)

    # Function body
    for stmt in func_ast.body:
        Stmt(stmt, codegen_ctx).lower()

    # If no explicit return, add stop/return
    if not builder.is_terminated():
        codegen_ctx.emit_nonreentrant_unlock(func_t)
        if func_t.return_type is None:
            builder.stop()
        else:
            # This shouldn't happen - function should have return stmt
            raise CompilerPanic("External function missing return")


def _register_positional_args(ctx: VenomCodegenContext, func_t: ContractFunctionT) -> None:
    """Register positional args from calldata.

    Uses ABI decoder to properly handle dynamic types (String, Bytes, DynArray)
    which require following offset pointers in the calldata.
    """
    if not func_t.positional_args:
        return

    # Create a tuple type for the positional args
    arg_types = [arg.typ for arg in func_t.positional_args]
    args_tuple_t = TupleT(tuple(arg_types))

    # Create VyperValue pointing to calldata tuple (starts at offset 4 after selector)
    ptr = Ptr(operand=IRLiteral(SELECTOR_BYTES), location=DataLocation.CALLDATA)
    calldata_tuple = VyperValue.from_ptr(ptr, args_tuple_t)

    for i, arg in enumerate(func_t.positional_args):
        # Calculate static offset for this element in the tuple
        static_offset = sum(
            func_t.positional_args[j].typ.abi_type.embedded_static_size() for j in range(i)
        )

        # Allocate memory for the arg
        var = ctx.new_variable(arg.name, arg.typ, mutable=False)

        # Get the element location in calldata (handles ABI offset indirection for dynamic types)
        elem_src = _getelemptr_abi(ctx, calldata_tuple, arg.typ, static_offset)

        # Decode from calldata to memory
        # Note: No hi bound needed - calldata size already validated in dispatcher
        abi_decode_to_buf(ctx, var.value.operand, elem_src)


def _handle_kwargs(
    ctx: VenomCodegenContext, func_t: ContractFunctionT, entry_info: EntryPointInfo
) -> None:
    """Allocate and initialize keyword arguments.

    Some come from calldata, some use default values.
    """
    if not func_t.keyword_args:
        return

    # Calculate which kwargs come from calldata
    # Based on entry_info.min_calldatasize, we can determine how many
    # kwargs were provided
    positional_size = sum(arg.typ.abi_type.embedded_static_size() for arg in func_t.positional_args)
    kwarg_bytes_from_calldata = entry_info.min_calldatasize - SELECTOR_BYTES - positional_size

    # Count kwargs by iterating and summing their actual ABI sizes
    # (can't divide by 32 since complex types like arrays have different sizes)
    kwargs_from_calldata = 0
    accumulated_size = 0
    for arg in func_t.keyword_args:
        if accumulated_size >= kwarg_bytes_from_calldata:
            break
        accumulated_size += arg.typ.abi_type.embedded_static_size()
        kwargs_from_calldata += 1

    # Create tuple type for args that come from calldata (positional + provided kwargs)
    calldata_arg_types: list[VyperType] = []
    if kwargs_from_calldata > 0:
        calldata_arg_types = [arg.typ for arg in func_t.positional_args]
        calldata_arg_types += [func_t.keyword_args[j].typ for j in range(kwargs_from_calldata)]
        calldata_tuple_t = TupleT(tuple(calldata_arg_types))
        ptr = Ptr(operand=IRLiteral(SELECTOR_BYTES), location=DataLocation.CALLDATA)
        calldata_tuple = VyperValue.from_ptr(ptr, calldata_tuple_t)

    for i, arg in enumerate(func_t.keyword_args):
        var = ctx.new_variable(arg.name, arg.typ, mutable=False)

        if i < kwargs_from_calldata:
            # Copy from calldata using ABI decoder
            # This kwarg's index in the full calldata tuple
            tuple_index = len(func_t.positional_args) + i
            static_offset = sum(
                calldata_arg_types[j].abi_type.embedded_static_size() for j in range(tuple_index)
            )
            elem_src = _getelemptr_abi(ctx, calldata_tuple, arg.typ, static_offset)
            abi_decode_to_buf(ctx, var.value.operand, elem_src)
        else:
            # Use default value
            default_node = func_t.default_values[arg.name]
            if arg.typ._is_prim_word:
                default_val = Expr(default_node, ctx).lower_value()
                ctx.ptr_store(var.value.ptr(), default_val)
            else:
                default_val = Expr(default_node, ctx).lower().operand
                ctx.store_memory(default_val, var.value.operand, arg.typ)


def _create_kwarg_allocas(
    builder: VenomBuilder, func_t: ContractFunctionT
) -> dict[str, IRVariable]:
    """Create allocas for kwargs, shared between entry points and common body.

    This must be called BEFORE generating entry points so the allocas exist
    in blocks that dominate both entry points and common body.

    Returns a dict mapping kwarg names to alloca IRVariables.
    The allocas are also stored in func_t._ir_info.kwarg_alloca_vars.
    """
    if func_t._ir_info.kwarg_alloca_vars is not None:
        return func_t._ir_info.kwarg_alloca_vars

    kwarg_vars: dict[str, IRVariable] = {}
    for arg in func_t.keyword_args:
        size = arg.typ.memory_bytes_required
        alloca_id = builder.ctx.get_next_alloca_id()
        ptr = builder.alloca(size, alloca_id)
        kwarg_vars[arg.name] = ptr

    func_t._ir_info.kwarg_alloca_vars = kwarg_vars
    return kwarg_vars


def _init_kwargs_in_entry_point(
    ctx: VenomCodegenContext, func_t: ContractFunctionT, entry_info: EntryPointInfo
) -> None:
    """Initialize keyword arguments in an entry point.

    Writes kwargs (from calldata or defaults) to the pre-allocated alloca locations.
    The allocas must have been created earlier via _create_kwarg_allocas.
    """
    if not func_t.keyword_args:
        return

    # Get the pre-created alloca variables
    kwarg_vars = func_t._ir_info.kwarg_alloca_vars
    assert kwarg_vars is not None, "kwarg allocas must be created before entry points"

    # Calculate which kwargs come from calldata
    positional_size = sum(arg.typ.abi_type.embedded_static_size() for arg in func_t.positional_args)
    kwarg_bytes_from_calldata = entry_info.min_calldatasize - SELECTOR_BYTES - positional_size

    # Count kwargs by iterating and summing their actual ABI sizes
    kwargs_from_calldata = 0
    accumulated_size = 0
    for arg in func_t.keyword_args:
        if accumulated_size >= kwarg_bytes_from_calldata:
            break
        accumulated_size += arg.typ.abi_type.embedded_static_size()
        kwargs_from_calldata += 1

    # Create tuple type for args that come from calldata (positional + provided kwargs)
    calldata_arg_types: list[VyperType] = []
    if kwargs_from_calldata > 0:
        calldata_arg_types = [arg.typ for arg in func_t.positional_args]
        calldata_arg_types += [func_t.keyword_args[j].typ for j in range(kwargs_from_calldata)]
        calldata_tuple_t = TupleT(tuple(calldata_arg_types))
        ptr = Ptr(operand=IRLiteral(SELECTOR_BYTES), location=DataLocation.CALLDATA)
        calldata_tuple = VyperValue.from_ptr(ptr, calldata_tuple_t)

    for i, arg in enumerate(func_t.keyword_args):
        # Get the pre-allocated alloca variable
        alloca_ptr = kwarg_vars[arg.name]

        if i < kwargs_from_calldata:
            # Copy from calldata using ABI decoder
            tuple_index = len(func_t.positional_args) + i
            static_offset = sum(
                calldata_arg_types[j].abi_type.embedded_static_size() for j in range(tuple_index)
            )
            elem_src = _getelemptr_abi(ctx, calldata_tuple, arg.typ, static_offset)
            abi_decode_to_buf(ctx, alloca_ptr, elem_src)
        else:
            # Use default value
            default_node = func_t.default_values[arg.name]
            if arg.typ._is_prim_word:
                default_val = Expr(default_node, ctx).lower_value()
                ctx.builder.mstore(alloca_ptr, default_val)
            else:
                default_val = Expr(default_node, ctx).lower().operand
                ctx.store_memory(default_val, alloca_ptr, arg.typ)


def _register_kwarg_variables(ctx: VenomCodegenContext, func_t: ContractFunctionT) -> None:
    """Register kwargs as variables in the common body context.

    The entry points have already written values to the shared allocas.
    This just registers those allocas as named variables - no allocation or copy.
    """
    if not func_t.keyword_args:
        return

    # Get the pre-created alloca variables
    kwarg_vars = func_t._ir_info.kwarg_alloca_vars
    assert kwarg_vars is not None, "kwarg allocas must be created before common body"

    for arg in func_t.keyword_args:
        # Get the alloca that entry points wrote to
        alloca_ptr = kwarg_vars[arg.name]

        # Register as a variable pointing to the existing alloca (no new allocation)
        ctx.register_variable(arg.name, arg.typ, alloca_ptr, mutable=False)


def _generate_fallback_body(
    builder: VenomBuilder,
    module_t: ModuleT,
    func_t: ContractFunctionT,
    func_ast: vy_ast.FunctionDef,
) -> None:
    """Generate the fallback (__default__) function body."""
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        constancy=_get_constancy(func_t),
        is_ctor_context=False,
    )

    # Nonreentrant lock
    codegen_ctx.emit_nonreentrant_lock(func_t)

    # Function body
    for stmt in func_ast.body:
        Stmt(stmt, codegen_ctx).lower()

    # Exit
    if not builder.is_terminated():
        codegen_ctx.emit_nonreentrant_unlock(func_t)
        if func_t.return_type is None:
            builder.stop()
        else:
            raise CompilerPanic("Fallback function with return type")


def _generate_internal_function(
    ir_ctx: IRContext,
    module_t: ModuleT,
    func_ast: vy_ast.FunctionDef,
    is_ctor_context: bool,
    immutables_len: int = 0,
    immutables_alloca_id: Optional[int] = None,
) -> None:
    """Generate an internal function."""
    func_t = func_ast._metadata["func_type"]
    _init_ir_info(func_t)

    # Generate function label
    suffix = "_deploy" if is_ctor_context else "_runtime"
    argz = ",".join([str(arg.typ) for arg in func_t.arguments])
    fn_label = f"internal {func_t._function_id} {func_t.name}({argz}){suffix}"

    # Create function in IR context
    fn = ir_ctx.create_function(fn_label)
    builder = VenomBuilder(ir_ctx, fn)

    # Create codegen context
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        constancy=_get_constancy(func_t),
        is_ctor_context=is_ctor_context,
    )

    # Reserve immutables region for ctor context internal functions.
    # Uses the SHARED alloca_id and explicitly sets position 0 to match
    # the constructor's allocation. This ensures all ctor-context functions
    # access immutables at the same memory location.
    if is_ctor_context and immutables_len > 0 and immutables_alloca_id is not None:
        codegen_ctx.immutables_alloca = builder.alloca(immutables_len, immutables_alloca_id)
        # Get the alloca instruction (just appended) and force position 0
        alloca_inst = builder._current_bb.instructions[-1]
        assert alloca_inst.opcode == "alloca", f"Expected alloca, got {alloca_inst.opcode}"
        imm_alloc = Allocation(alloca_inst)
        builder.ctx.mem_allocator.set_position(imm_alloc, 0)
        # Keep ctor immutables region reserved in all functions so local
        # allocas in ctor-context internal calls cannot overlap it.
        builder.ctx.mem_allocator.add_global(imm_alloc)

    # Set up return handling
    pass_via_stack = codegen_ctx.pass_via_stack(func_t)
    returns_count = codegen_ctx.returns_stack_count(func_t)
    has_memory_return_buffer = func_t.return_type is not None and returns_count == 0

    # Structured invoke metadata used by backend passes.
    fn._has_memory_return_buffer_param = has_memory_return_buffer
    fn._invoke_param_count = len(func_t.arguments) + (1 if has_memory_return_buffer else 0)

    # Handle parameters
    # First: return buffer pointer if memory return
    if has_memory_return_buffer:
        codegen_ctx.return_buffer = builder.param()

    # Handle function arguments
    for arg in func_t.arguments:
        if pass_via_stack[arg.name]:
            # Stack-passed: receive value, allocate memory, store
            val = builder.param()
            var = codegen_ctx.new_variable(arg.name, arg.typ, mutable=True)
            codegen_ctx.ptr_store(var.value.ptr(), val)
        else:
            # Memory-passed: receive pointer, register directly (no allocation)
            ptr = builder.param()
            codegen_ctx.register_variable(arg.name, arg.typ, ptr, mutable=True)

    # Return PC is last param
    codegen_ctx.return_pc = builder.param()

    # Allocate return buffer if needed
    if func_t.return_type is not None:
        if returns_count > 0:
            ret_buf = codegen_ctx.new_temporary_value(func_t.return_type).operand
            assert isinstance(ret_buf, IRVariable)
            codegen_ctx.return_buffer = ret_buf

    # Nonreentrant lock
    codegen_ctx.emit_nonreentrant_lock(func_t)

    # Function body
    for stmt in func_ast.body:
        Stmt(stmt, codegen_ctx).lower()

    # Default return if not terminated
    if not builder.is_terminated():
        codegen_ctx.emit_nonreentrant_unlock(func_t)
        if func_t.return_type is None:
            builder.ret(codegen_ctx.return_pc)
        else:
            raise CompilerPanic("Internal function missing return")


def _generate_constructor(
    builder: VenomBuilder,
    module_t: ModuleT,
    func_ast: vy_ast.FunctionDef,
    runtime_codesize: int,
    immutables_len: int,
    immutables_alloca_id: Optional[int],
) -> None:
    """Generate constructor (deploy) code."""
    func_t = func_ast._metadata["func_type"]
    _init_ir_info(func_t)

    # Create codegen context
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        constancy=_get_constancy(func_t),
        is_ctor_context=True,
    )

    # Payable check
    if not func_t.is_payable:
        callvalue = builder.callvalue()
        is_zero = builder.iszero(callvalue)
        builder.assert_(is_zero)

    # Reserve immutables region at memory position 0.
    # Immutables MUST be at position 0 because:
    # 1. The deploy epilogue copies from position 0 to the bytecode
    # 2. Runtime dload(0) reads from code_end + 0
    #
    # We explicitly set the position to 0 using mem_allocator.set_position()
    # to bypass the normal allocation algorithm. This matches the legacy
    # codegen behavior.
    # (GH issue 3101)
    if immutables_len > 0 and immutables_alloca_id is not None:
        codegen_ctx.immutables_alloca = builder.alloca(immutables_len, immutables_alloca_id)
        # Get the alloca instruction (just appended) and force position 0
        alloca_inst = builder._current_bb.instructions[-1]
        assert alloca_inst.opcode == "alloca", f"Expected alloca, got {alloca_inst.opcode}"
        imm_alloc = Allocation(alloca_inst)
        builder.ctx.mem_allocator.set_position(imm_alloc, 0)
        # Reserve immutables memory globally so later function concretization
        # never reuses this region for temporary allocas.
        builder.ctx.mem_allocator.add_global(imm_alloc)

        # Force msize to be past immutables region (like legacy's GH issue 3101 fix)
        # This ensures builtins using msize() don't clobber immutables
        # mload X touches bytes X to X+32, so touch the last word
        touch_offset = max(0, immutables_len - 32)
        builder.mload(IRLiteral(touch_offset))

    # Register constructor args from DATA section (not calldata)
    # Constructor args are appended to the deploy code
    _register_constructor_args(codegen_ctx, func_t)

    # Nonreentrant lock
    codegen_ctx.emit_nonreentrant_lock(func_t)

    # Constructor body
    for stmt in func_ast.body:
        Stmt(stmt, codegen_ctx).lower()

    # Unlock
    if not builder.is_terminated():
        codegen_ctx.emit_nonreentrant_unlock(func_t)

        # Deploy epilogue: copy runtime code to memory and return
        _emit_deploy_epilogue(
            builder, runtime_codesize, immutables_len, codegen_ctx.immutables_alloca
        )


def _register_constructor_args(ctx: VenomCodegenContext, func_t: ContractFunctionT) -> None:
    """Register constructor args from DATA section.

    Uses ABI decoder to properly handle dynamic types (String, Bytes, DynArray)
    which require following offset pointers in the data section.
    """
    if not func_t.positional_args:
        return

    # Create a tuple type for the positional args
    arg_types = [arg.typ for arg in func_t.positional_args]
    args_tuple_t = TupleT(tuple(arg_types))

    # Create VyperValue pointing to data section tuple (starts at offset 0)
    ptr = Ptr(operand=IRLiteral(0), location=DataLocation.CODE)
    data_tuple = VyperValue.from_ptr(ptr, args_tuple_t)

    for i, arg in enumerate(func_t.positional_args):
        # Calculate static offset for this element in the tuple
        static_offset = sum(
            func_t.positional_args[j].typ.abi_type.embedded_static_size() for j in range(i)
        )

        # Allocate memory for the arg
        var = ctx.new_variable(arg.name, arg.typ, mutable=False)

        # Get element location in data section (handles ABI offset for dynamic types)
        elem_src = _getelemptr_abi(ctx, data_tuple, arg.typ, static_offset)

        # Decode from data section to memory
        # Note: No hi bound needed for constructor args from trusted bytecode
        abi_decode_to_buf(ctx, var.value.operand, elem_src)


def _generate_simple_deploy(
    builder: VenomBuilder, runtime_codesize: int, immutables_len: int
) -> None:
    """Generate simple deploy code (no constructor)."""
    # Just emit the deploy epilogue - no immutables alloca since no constructor
    _emit_deploy_epilogue(builder, runtime_codesize, immutables_len, None)


def _emit_deploy_epilogue(
    builder: VenomBuilder,
    runtime_codesize: int,
    immutables_len: int,
    immutables_alloca: Optional[IRVariable],
) -> None:
    """
    Copy runtime bytecode to memory and return it.
    """
    # Dynamically allocate memory for runtime code + immutables
    total_size = runtime_codesize + immutables_len
    alloca_id = builder.ctx.get_next_alloca_id()
    dst_ptr = builder.alloca(total_size, alloca_id)

    # Copy immutables from deployment memory to runtime position
    if immutables_len > 0:
        immutables_dst = builder.add(dst_ptr, IRLiteral(runtime_codesize))

        # Source is the immutables_alloca if available, otherwise offset 0
        immutables_src: IROperand = (
            immutables_alloca if immutables_alloca is not None else IRLiteral(0)
        )

        if version_check(begin="cancun"):
            # Cancun+: use mcopy
            builder.mcopy(immutables_dst, immutables_src, IRLiteral(immutables_len))
        else:
            # Pre-Cancun: use identity precompile (0x04)
            # staticcall(gas, 0x04, src, len, dst, len)
            gas = builder.gas()
            copy_success = builder.staticcall(
                gas,
                IRLiteral(0x04),  # Identity precompile
                immutables_src,
                IRLiteral(immutables_len),
                immutables_dst,
                IRLiteral(immutables_len),
            )
            builder.assert_(copy_success)

    # Copy runtime bytecode from data section to memory
    builder.codecopy(dst_ptr, IRLabel("runtime_begin"), IRLiteral(runtime_codesize))

    # Return runtime + immutables
    builder.return_(dst_ptr, IRLiteral(total_size))
