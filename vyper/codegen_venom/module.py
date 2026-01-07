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
from vyper.codegen.core import needs_clamp
from vyper.codegen.function_definitions.common import EntryPointInfo, _FuncIRInfo
from vyper.codegen.ir_node import Encoding
from vyper.codegen_venom.abi.abi_decoder import _getelemptr_abi, abi_decode_to_buf
from vyper.codegen_venom.buffer import Ptr
from vyper.codegen_venom.constants import SELECTOR_BYTES, SELECTOR_SHIFT_BITS
from vyper.codegen_venom.value import VyperValue
from vyper.semantics.data_locations import DataLocation
from vyper.compiler.settings import Settings
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import TupleT, VyperType
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.utils import OrderedSet, method_id_int
from vyper.venom.basicblock import IRLabel, IRLiteral
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext

from .context import VenomCodegenContext
from .expr import Expr
from .stmt import Stmt


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
    _generate_selector_section_linear(
        runtime_builder, module_t, external_functions, default_function
    )

    # Generate internal functions for runtime
    for func_ast in internal_functions:
        _generate_internal_function(runtime_ctx, module_t, func_ast, is_ctor_context=False)

    return runtime_ctx


def generate_deploy_venom(
    module_t: ModuleT, settings: Settings, runtime_bytecode: bytes, immutables_len: int
) -> IRContext:
    """
    Generate deploy Venom IR with embedded runtime bytecode.

    This is phase 2 of the two-phase compilation. The runtime
    bytecode is embedded as a data section and the deploy epilogue
    copies it to memory and returns it.
    """
    id_generator = IDGenerator()

    # Create deploy IR context
    deploy_ctx = IRContext()

    # Add runtime bytecode as data section
    deploy_ctx.append_data_section(IRLabel("runtime_begin"))
    deploy_ctx.append_data_item(runtime_bytecode)

    deploy_fn = deploy_ctx.create_function("deploy")
    deploy_ctx.entry_function = deploy_fn  # Mark as entry point
    deploy_builder = VenomBuilder(deploy_ctx, deploy_fn)

    init_func_t = module_t.init_function

    if init_func_t is not None:
        id_generator.ensure_id(init_func_t)

        # Assign IDs to reachable internal functions from constructor
        for func_t in init_func_t.reachable_internal_functions:
            id_generator.ensure_id(func_t)

        # Generate constructor
        assert isinstance(init_func_t.ast_def, vy_ast.FunctionDef)
        _generate_constructor(
            deploy_builder, module_t, init_func_t.ast_def, len(runtime_bytecode), immutables_len
        )

        # Generate internal functions reachable from constructor
        for func_t in init_func_t.reachable_internal_functions:
            _generate_internal_function(deploy_ctx, module_t, func_t.ast_def, is_ctor_context=True)
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

    # Generate entry points and dispatch checks
    for func_ast in external_functions:
        func_t = func_ast._metadata["func_type"]
        _init_ir_info(func_t)

        # Generate entry points for all ABI signatures (kwargs create multiple)
        entry_points = _generate_external_entry_points(func_t)

        for abi_sig, entry_info in entry_points.items():
            method_id_val = method_id_int(abi_sig)

            # Create block for this function's dispatch
            match_bb = builder.create_block(f"match_{method_id_val:08x}")

            # Check if method_id matches
            is_match = builder.eq(method_id, IRLiteral(method_id_val))

            # Create next check block
            next_check_bb = builder.create_block("next_check")

            builder.jnz(is_match, match_bb.label, next_check_bb.label)

            # Match block: payable/calldatasize checks, then function body
            builder.append_block(match_bb)
            builder.set_block(match_bb)

            _emit_entry_checks(builder, func_t, entry_info.min_calldatasize)

            # Generate function body (entry point + common code)
            _generate_external_function_body(builder, module_t, func_t, func_ast, entry_info)

            # Continue checking other functions
            builder.append_block(next_check_bb)
            builder.set_block(next_check_bb)

    # No match found - goto fallback
    builder.jmp(fallback_bb.label)

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
        module_ctx=module_t, builder=builder, func_t=func_t, is_ctor_context=False
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


def _register_positional_args(ctx: VenomCodegenContext, func_t: ContractFunctionT) -> None:
    """Register positional args from calldata.

    Uses ABI decoder to properly handle dynamic types (String, Bytes, DynArray)
    which require following offset pointers in the calldata.
    """
    if not func_t.positional_args:
        return

    # Create a tuple type for the positional args
    arg_types = [arg.typ for arg in func_t.positional_args]
    args_tuple_t = TupleT(arg_types)

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
    if kwargs_from_calldata > 0:
        calldata_arg_types = [arg.typ for arg in func_t.positional_args]
        calldata_arg_types += [func_t.keyword_args[j].typ for j in range(kwargs_from_calldata)]
        calldata_tuple_t = TupleT(calldata_arg_types)
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


def _generate_fallback_body(
    builder: VenomBuilder,
    module_t: ModuleT,
    func_t: ContractFunctionT,
    func_ast: vy_ast.FunctionDef,
) -> None:
    """Generate the fallback (__default__) function body."""
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t, builder=builder, func_t=func_t, is_ctor_context=False
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
    ir_ctx: IRContext, module_t: ModuleT, func_ast: vy_ast.FunctionDef, is_ctor_context: bool
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
        module_ctx=module_t, builder=builder, func_t=func_t, is_ctor_context=is_ctor_context
    )

    # Set up return handling
    pass_via_stack = codegen_ctx.pass_via_stack(func_t)
    returns_count = codegen_ctx.returns_stack_count(func_t)

    # Handle parameters
    # First: return buffer pointer if memory return
    if func_t.return_type is not None and returns_count == 0:
        codegen_ctx.return_buffer = builder.param()

    # Handle function arguments
    for arg in func_t.arguments:
        if pass_via_stack[arg.name]:
            # Stack-passed: receive value, allocate memory, store
            val = builder.param()
            var = codegen_ctx.new_variable(arg.name, arg.typ, mutable=False)
            codegen_ctx.ptr_store(var.value.ptr(), val)
        else:
            # Memory-passed: receive pointer, register directly (no allocation)
            ptr = builder.param()
            codegen_ctx.register_variable(arg.name, arg.typ, ptr, mutable=False)

    # Return PC is last param
    codegen_ctx.return_pc = builder.param()

    # Allocate return buffer if needed
    if func_t.return_type is not None:
        if returns_count > 0:
            codegen_ctx.return_buffer = codegen_ctx.new_temporary_value(func_t.return_type).operand

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
) -> None:
    """Generate constructor (deploy) code."""
    func_t = func_ast._metadata["func_type"]
    _init_ir_info(func_t)

    # Create codegen context
    codegen_ctx = VenomCodegenContext(
        module_ctx=module_t, builder=builder, func_t=func_t, is_ctor_context=True
    )

    # Payable check
    if not func_t.is_payable:
        callvalue = builder.callvalue()
        is_zero = builder.iszero(callvalue)
        builder.assert_(is_zero)

    # Ensure msize covers immutables (GH issue 3101)
    # This is needed because immutable writes use istore which
    # relies on msize tracking the immutables region
    if immutables_len > 0:
        builder.mload(IRLiteral(max(0, immutables_len - 32)))

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
    _emit_deploy_epilogue(builder, runtime_codesize, immutables_len)


def _register_constructor_args(ctx: VenomCodegenContext, func_t: ContractFunctionT) -> None:
    """Register constructor args from DATA section."""
    # Constructor args are at offset 0 in the DATA section
    # (appended after deploy code)
    offset = 0

    for arg in func_t.positional_args:
        var = ctx.new_variable(arg.name, arg.typ, mutable=False)

        if arg.typ._is_prim_word:
            val = ctx.builder.dload(IRLiteral(offset))
            ctx.ptr_store(var.value.ptr(), val)
        else:
            size = arg.typ.memory_bytes_required
            ctx.builder.dloadbytes(var.value.operand, IRLiteral(offset), IRLiteral(size))

        offset += arg.typ.abi_type.embedded_static_size()


def _generate_simple_deploy(
    builder: VenomBuilder, runtime_codesize: int, immutables_len: int
) -> None:
    """Generate simple deploy code (no constructor)."""
    # Just emit the deploy epilogue
    _emit_deploy_epilogue(builder, runtime_codesize, immutables_len)


def _emit_deploy_epilogue(
    builder: VenomBuilder, runtime_codesize: int, immutables_len: int
) -> None:
    """
    Copy runtime bytecode to memory and return it.

    Memory layout (matching legacy):
    [0-63]: Reserved (FREE_VAR_SPACE)
    [64-...]: Runtime code
    [64+runtime_codesize-...]: Immutables
    """
    DST_OFFSET = 64  # After FREE_VAR_SPACE

    # Copy immutables from deployment memory to runtime position
    if immutables_len > 0:
        immutables_dst = IRLiteral(DST_OFFSET + runtime_codesize)

        if version_check(begin="cancun"):
            # Cancun+: use mcopy
            # mcopy(dst, src, size) - src is 0 (immutables at start of memory)
            builder.mcopy(immutables_dst, IRLiteral(0), IRLiteral(immutables_len))
        else:
            # Pre-Cancun: use identity precompile (0x04)
            # staticcall(gas, 0x04, src, len, dst, len)
            gas = builder.gas()
            copy_success = builder.staticcall(
                gas,
                IRLiteral(0x04),  # Identity precompile
                IRLiteral(0),  # Source (immutables region)
                IRLiteral(immutables_len),
                immutables_dst,
                IRLiteral(immutables_len),
            )
            builder.assert_(copy_success)

    # Copy runtime bytecode from data section to memory
    builder.codecopy(IRLiteral(DST_OFFSET), IRLabel("runtime_begin"), IRLiteral(runtime_codesize))

    # Return runtime + immutables
    total_size = builder.add(IRLiteral(runtime_codesize), IRLiteral(immutables_len))
    builder.return_(IRLiteral(DST_OFFSET), total_size)
