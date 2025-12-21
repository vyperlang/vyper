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
from typing import Optional

import vyper.ast as vy_ast
from vyper.codegen import core
from vyper.codegen.abi_encoder import abi_encoding_matches_vyper
from vyper.codegen.core import needs_clamp
from vyper.codegen.function_definitions.common import (
    EntryPointInfo,
    ExternalFuncIR,
    FrameInfo,
    _FuncIRInfo,
)
from vyper.codegen.ir_node import Encoding
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
from vyper.venom.function import IRFunction

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
    ret = OrderedSet()

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


class VenomModuleCompiler:
    """Compile a Vyper module to Venom IR."""

    def __init__(self, module_t: ModuleT):
        self.module_t = module_t
        self.id_generator = IDGenerator()

        # Venom IR context (shared across functions)
        self.ir_ctx = IRContext()

    def compile(self) -> tuple[IRContext, IRContext]:
        """Compile module to deploy and runtime IR contexts.

        Returns (deploy_ir_ctx, runtime_ir_ctx).
        """
        runtime_reachable = _runtime_reachable_functions(
            self.module_t, self.id_generator
        )

        function_defs = [fn_t.ast_def for fn_t in runtime_reachable]

        runtime_functions = [f for f in function_defs if not _is_constructor(f)]
        internal_functions = [f for f in runtime_functions if _is_internal(f)]
        external_functions = [
            f
            for f in runtime_functions
            if not _is_internal(f) and not _is_fallback(f)
        ]
        default_function = next(
            (f for f in runtime_functions if _is_fallback(f)), None
        )

        # Create runtime IR context
        runtime_ctx = IRContext()
        runtime_fn = runtime_ctx.create_function("runtime")
        runtime_builder = VenomBuilder(runtime_ctx, runtime_fn)

        # Generate selector dispatch
        self._generate_selector_section_linear(
            runtime_builder, external_functions, default_function
        )

        # Generate internal functions for runtime
        for func_ast in internal_functions:
            self._generate_internal_function(
                runtime_ctx, func_ast, is_ctor_context=False
            )

        # Create deploy IR context
        deploy_ctx = IRContext()
        deploy_fn = deploy_ctx.create_function("deploy")
        deploy_builder = VenomBuilder(deploy_ctx, deploy_fn)

        init_func_t = self.module_t.init_function
        if init_func_t is not None:
            self.id_generator.ensure_id(init_func_t)

            # Generate constructor internal functions
            for func_t in init_func_t.reachable_internal_functions:
                self.id_generator.ensure_id(func_t)
                self._generate_internal_function(
                    deploy_ctx, func_t.ast_def, is_ctor_context=True
                )

            # Generate constructor
            self._generate_constructor(
                deploy_builder, init_func_t.ast_def, runtime_ctx
            )
        else:
            # No constructor - just deploy runtime
            self._generate_simple_deploy(deploy_builder, runtime_ctx)

        return deploy_ctx, runtime_ctx

    def _generate_selector_section_linear(
        self,
        builder: VenomBuilder,
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
        # Check calldatasize >= 4
        calldatasize = builder.calldatasize()
        has_selector = builder.iszero(builder.lt(calldatasize, IRLiteral(4)))

        fallback_label = builder.label("fallback")
        dispatch_label = builder.label("dispatch")

        # If calldatasize < 4, goto fallback
        dispatch_bb = builder.create_block("dispatch")
        fallback_bb = builder.create_block("fallback")

        builder.jnz(has_selector, dispatch_bb.label, fallback_bb.label)

        # Dispatch block: load selector and check functions
        builder.append_block(dispatch_bb)
        builder.set_block(dispatch_bb)

        # _calldata_method_id = shr(224, calldataload(0))
        raw_selector = builder.calldataload(IRLiteral(0))
        method_id = builder.shr(IRLiteral(224), raw_selector)

        # Generate entry points and dispatch checks
        for func_ast in external_functions:
            func_t = func_ast._metadata["func_type"]
            _init_ir_info(func_t)

            # Generate entry points for all ABI signatures (kwargs create multiple)
            entry_points = self._generate_external_entry_points(
                builder.ctx, func_t, func_ast
            )

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

                self._emit_entry_checks(builder, func_t, entry_info.min_calldatasize)

                # Generate function body (entry point + common code)
                self._generate_external_function_body(
                    builder, func_t, func_ast, entry_info
                )

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
            self._generate_fallback_body(builder, func_t, default_function)
        else:
            # No fallback - revert
            builder.revert(IRLiteral(0), IRLiteral(0))

    def _emit_entry_checks(
        self, builder: VenomBuilder, func_t: ContractFunctionT, min_calldatasize: int
    ) -> None:
        """Emit payable and calldatasize checks for external function entry."""
        # Payable check
        if not func_t.is_payable:
            callvalue = builder.callvalue()
            is_zero = builder.iszero(callvalue)
            builder.assert_(is_zero)

        # Calldatasize check
        if min_calldatasize > 4:
            calldatasize = builder.calldatasize()
            is_enough = builder.iszero(
                builder.lt(calldatasize, IRLiteral(min_calldatasize))
            )
            builder.assert_(is_enough)

    def _generate_external_entry_points(
        self,
        ir_ctx: IRContext,
        func_t: ContractFunctionT,
        func_ast: vy_ast.FunctionDef,
    ) -> dict[str, EntryPointInfo]:
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

        # Calculate base args tuple type
        base_args_t = TupleT(tuple(arg.typ for arg in positional_args))

        # Generate entry point for each kwarg combination
        for i in range(len(keyword_args) + 1):
            calldata_kwargs = keyword_args[:i]
            default_kwargs = keyword_args[i:]

            calldata_args = positional_args + calldata_kwargs
            calldata_args_t = TupleT(tuple(arg.typ for arg in calldata_args))

            abi_sig = func_t.abi_signature_for_kwargs(calldata_kwargs)
            min_calldatasize = 4 + calldata_args_t.abi_type.static_size()

            entry_points[abi_sig] = EntryPointInfo(
                func_t=func_t,
                min_calldatasize=min_calldatasize,
                ir_node=None,  # We generate IR directly, not via IRnode
            )

        return entry_points

    def _generate_external_function_body(
        self,
        builder: VenomBuilder,
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
            module_ctx=self.module_t,
            builder=builder,
            func_t=func_t,
            is_ctor_context=False,
        )

        # Register positional args from calldata
        self._register_positional_args(codegen_ctx, func_t)

        # Handle kwargs (allocate memory, copy from calldata or defaults)
        self._handle_kwargs(codegen_ctx, func_t, entry_info)

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

    def _register_positional_args(
        self, ctx: VenomCodegenContext, func_t: ContractFunctionT
    ) -> None:
        """Register positional args from calldata.

        For types that need clamping: copy to memory with validation.
        For safe types: leave in calldata (no allocation).
        """
        # Base args start at offset 4 (after selector)
        base_offset = 4

        base_args_t = TupleT(tuple(arg.typ for arg in func_t.positional_args))

        for i, arg in enumerate(func_t.positional_args):
            # Calculate offset into calldata tuple
            static_offset = sum(
                func_t.positional_args[j].typ.abi_type.embedded_static_size()
                for j in range(i)
            )
            calldata_offset = base_offset + static_offset

            if needs_clamp(arg.typ, Encoding.ABI):
                # Needs validation - copy to memory
                ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)
                self._copy_from_calldata(ctx, ptr, calldata_offset, arg.typ)
            else:
                # Safe to leave in calldata - just track the offset
                # For now, we allocate memory for all args (simpler)
                # TODO: Optimize to leave safe types in calldata
                ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)
                val = ctx.load_calldata(IRLiteral(calldata_offset), arg.typ)
                if arg.typ._is_prim_word:
                    ctx.builder.mstore(val, ptr)
                else:
                    # Complex type already in memory from load_calldata
                    pass

    def _copy_from_calldata(
        self,
        ctx: VenomCodegenContext,
        ptr,
        offset: int,
        typ: VyperType,
    ) -> None:
        """Copy value from calldata to memory with ABI decoding.

        For static types: simple calldataload/mstore.
        For dynamic types: handle indirection and validate bounds.
        """
        builder = ctx.builder

        if typ._is_prim_word:
            # Simple 32-byte word
            val = builder.calldataload(IRLiteral(offset))
            # TODO: Add clamping/validation for types that need it
            builder.mstore(val, ptr)
        else:
            # Complex type - copy to memory
            size = typ.memory_bytes_required
            builder.calldatacopy(IRLiteral(size), IRLiteral(offset), ptr)
            # TODO: Add validation for dynamic types

    def _handle_kwargs(
        self,
        ctx: VenomCodegenContext,
        func_t: ContractFunctionT,
        entry_info: EntryPointInfo,
    ) -> None:
        """Allocate and initialize keyword arguments.

        Some come from calldata, some use default values.
        """
        # Calculate which kwargs come from calldata
        # Based on entry_info.min_calldatasize, we can determine how many
        # kwargs were provided

        positional_size = sum(
            arg.typ.abi_type.embedded_static_size() for arg in func_t.positional_args
        )
        kwargs_from_calldata = (entry_info.min_calldatasize - 4 - positional_size) // 32

        # This is a simplification - real kwargs calculation is more complex
        # for dynamic types. For now, allocate all kwargs and fill appropriately.

        base_offset = 4 + positional_size

        for i, arg in enumerate(func_t.keyword_args):
            ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)

            if i < kwargs_from_calldata:
                # Copy from calldata
                static_offset = sum(
                    func_t.keyword_args[j].typ.abi_type.embedded_static_size()
                    for j in range(i)
                )
                calldata_offset = base_offset + static_offset
                self._copy_from_calldata(ctx, ptr, calldata_offset, arg.typ)
            else:
                # Use default value
                default_node = func_t.default_values[arg.name]
                default_val = Expr(default_node, ctx).lower()
                if arg.typ._is_prim_word:
                    ctx.builder.mstore(default_val, ptr)
                else:
                    ctx.store_memory(default_val, ptr, arg.typ)

    def _generate_fallback_body(
        self,
        builder: VenomBuilder,
        func_t: ContractFunctionT,
        func_ast: vy_ast.FunctionDef,
    ) -> None:
        """Generate the fallback (__default__) function body."""
        codegen_ctx = VenomCodegenContext(
            module_ctx=self.module_t,
            builder=builder,
            func_t=func_t,
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
        self,
        ir_ctx: IRContext,
        func_ast: vy_ast.FunctionDef,
        is_ctor_context: bool,
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
            module_ctx=self.module_t,
            builder=builder,
            func_t=func_t,
            is_ctor_context=is_ctor_context,
        )

        # Set up return handling
        pass_via_stack = codegen_ctx.pass_via_stack(func_t)
        returns_count = codegen_ctx.returns_stack_count(func_t)

        # Handle parameters
        # First: return buffer pointer if memory return
        if func_t.return_type is not None and returns_count == 0:
            codegen_ctx.return_buffer = builder.param()

        # Stack-passed args come as params
        for arg in func_t.arguments:
            if pass_via_stack[arg.name]:
                val = builder.param()
                ptr = codegen_ctx.new_variable(arg.name, arg.typ, mutable=False)
                builder.mstore(val, ptr)

        # Return PC is last param
        codegen_ctx.return_pc = builder.param()

        # Allocate return buffer if needed
        if func_t.return_type is not None:
            if returns_count > 0:
                codegen_ctx.return_buffer = codegen_ctx.new_internal_variable(
                    func_t.return_type
                )

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
        self,
        builder: VenomBuilder,
        func_ast: vy_ast.FunctionDef,
        runtime_ctx: IRContext,
    ) -> None:
        """Generate constructor (deploy) code."""
        func_t = func_ast._metadata["func_type"]
        _init_ir_info(func_t)

        # Create codegen context
        codegen_ctx = VenomCodegenContext(
            module_ctx=self.module_t,
            builder=builder,
            func_t=func_t,
            is_ctor_context=True,
        )

        # Payable check
        if not func_t.is_payable:
            callvalue = builder.callvalue()
            is_zero = builder.iszero(callvalue)
            builder.assert_(is_zero)

        # Register constructor args from DATA section (not calldata)
        # Constructor args are appended to the deploy code
        self._register_constructor_args(codegen_ctx, func_t)

        # Nonreentrant lock
        codegen_ctx.emit_nonreentrant_lock(func_t)

        # Constructor body
        for stmt in func_ast.body:
            Stmt(stmt, codegen_ctx).lower()

        # Unlock
        if not builder.is_terminated():
            codegen_ctx.emit_nonreentrant_unlock(func_t)

        # Deploy runtime code
        # TODO: Emit deploy instruction that copies runtime to memory and returns
        # For now, just stop
        builder.stop()

    def _register_constructor_args(
        self, ctx: VenomCodegenContext, func_t: ContractFunctionT
    ) -> None:
        """Register constructor args from DATA section."""
        # Constructor args are at offset 0 in the DATA section
        # (appended after deploy code)
        offset = 0

        for arg in func_t.positional_args:
            ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)

            if arg.typ._is_prim_word:
                val = ctx.builder.dload(IRLiteral(offset))
                ctx.builder.mstore(val, ptr)
            else:
                size = arg.typ.memory_bytes_required
                ctx.builder.dloadbytes(IRLiteral(size), IRLiteral(offset), ptr)

            offset += arg.typ.abi_type.embedded_static_size()

    def _generate_simple_deploy(
        self, builder: VenomBuilder, runtime_ctx: IRContext
    ) -> None:
        """Generate simple deploy code (no constructor)."""
        # Note: This legacy method just stops - proper deploy epilogue
        # is in the new _generate_simple_deploy() module-level function
        builder.stop()


def generate_ir_for_module(module_t: ModuleT) -> tuple[IRContext, IRContext]:
    """Legacy wrapper - generates incomplete IR for testing.

    For production use, prefer the two-phase API:
    - generate_runtime_venom() for runtime code
    - generate_deploy_venom() for deploy code with runtime bytecode

    Returns (deploy_ctx, runtime_ctx) - note the deploy ctx lacks
    the deploy epilogue and runtime bytecode embedding.
    """
    compiler = VenomModuleCompiler(module_t)
    return compiler.compile()


# =============================================================================
# Public API: Two-phase compilation
# =============================================================================


def generate_runtime_venom(
    module_t: ModuleT,
    settings: Settings,
) -> IRContext:
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
        f
        for f in runtime_functions
        if not _is_internal(f) and not _is_fallback(f)
    ]
    default_function = next(
        (f for f in runtime_functions if _is_fallback(f)), None
    )

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
        _generate_internal_function(
            runtime_ctx, module_t, func_ast, is_ctor_context=False
        )

    return runtime_ctx


def generate_deploy_venom(
    module_t: ModuleT,
    settings: Settings,
    runtime_bytecode: bytes,
    immutables_len: int,
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
        _generate_constructor(
            deploy_builder,
            module_t,
            init_func_t.ast_def,
            len(runtime_bytecode),
            immutables_len,
        )

        # Generate internal functions reachable from constructor
        for func_t in init_func_t.reachable_internal_functions:
            _generate_internal_function(
                deploy_ctx, module_t, func_t.ast_def, is_ctor_context=True
            )
    else:
        # No constructor - just deploy runtime
        _generate_simple_deploy(
            deploy_builder,
            len(runtime_bytecode),
            immutables_len,
        )

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
    # Check calldatasize >= 4
    calldatasize = builder.calldatasize()
    has_selector = builder.iszero(builder.lt(calldatasize, IRLiteral(4)))

    dispatch_bb = builder.create_block("dispatch")
    fallback_bb = builder.create_block("fallback")

    # If calldatasize < 4, goto fallback
    builder.jnz(has_selector, dispatch_bb.label, fallback_bb.label)

    # Dispatch block: load selector and check functions
    builder.append_block(dispatch_bb)
    builder.set_block(dispatch_bb)

    # _calldata_method_id = shr(224, calldataload(0))
    raw_selector = builder.calldataload(IRLiteral(0))
    method_id = builder.shr(IRLiteral(224), raw_selector)

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
            _generate_external_function_body(
                builder, module_t, func_t, func_ast, entry_info
            )

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
    if min_calldatasize > 4:
        calldatasize = builder.calldatasize()
        is_enough = builder.iszero(
            builder.lt(calldatasize, IRLiteral(min_calldatasize))
        )
        builder.assert_(is_enough)


def _generate_external_entry_points(
    func_t: ContractFunctionT,
) -> dict[str, EntryPointInfo]:
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
        min_calldatasize = 4 + calldata_args_t.abi_type.static_size()

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


def _register_positional_args(
    ctx: VenomCodegenContext, func_t: ContractFunctionT
) -> None:
    """Register positional args from calldata.

    For types that need clamping: copy to memory with validation.
    For safe types: leave in calldata (no allocation).
    """
    # Base args start at offset 4 (after selector)
    base_offset = 4

    for i, arg in enumerate(func_t.positional_args):
        # Calculate offset into calldata tuple
        static_offset = sum(
            func_t.positional_args[j].typ.abi_type.embedded_static_size()
            for j in range(i)
        )
        calldata_offset = base_offset + static_offset

        if needs_clamp(arg.typ, Encoding.ABI):
            # Needs validation - copy to memory
            ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)
            _copy_from_calldata(ctx, ptr, calldata_offset, arg.typ)
        else:
            # Safe to leave in calldata - just track the offset
            # For now, we allocate memory for all args (simpler)
            # TODO: Optimize to leave safe types in calldata
            ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)
            val = ctx.load_calldata(IRLiteral(calldata_offset), arg.typ)
            if arg.typ._is_prim_word:
                ctx.builder.mstore(val, ptr)
            else:
                # Complex type already in memory from load_calldata
                pass


def _copy_from_calldata(
    ctx: VenomCodegenContext,
    ptr,
    offset: int,
    typ: VyperType,
) -> None:
    """Copy value from calldata to memory with ABI decoding.

    For static types: simple calldataload/mstore.
    For dynamic types: handle indirection and validate bounds.
    """
    builder = ctx.builder

    if typ._is_prim_word:
        # Simple 32-byte word
        val = builder.calldataload(IRLiteral(offset))
        # TODO: Add clamping/validation for types that need it
        builder.mstore(val, ptr)
    else:
        # Complex type - copy to memory
        size = typ.memory_bytes_required
        builder.calldatacopy(IRLiteral(size), IRLiteral(offset), ptr)
        # TODO: Add validation for dynamic types


def _handle_kwargs(
    ctx: VenomCodegenContext,
    func_t: ContractFunctionT,
    entry_info: EntryPointInfo,
) -> None:
    """Allocate and initialize keyword arguments.

    Some come from calldata, some use default values.
    """
    # Calculate which kwargs come from calldata
    # Based on entry_info.min_calldatasize, we can determine how many
    # kwargs were provided

    positional_size = sum(
        arg.typ.abi_type.embedded_static_size() for arg in func_t.positional_args
    )
    kwargs_from_calldata = (entry_info.min_calldatasize - 4 - positional_size) // 32

    # This is a simplification - real kwargs calculation is more complex
    # for dynamic types. For now, allocate all kwargs and fill appropriately.

    base_offset = 4 + positional_size

    for i, arg in enumerate(func_t.keyword_args):
        ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)

        if i < kwargs_from_calldata:
            # Copy from calldata
            static_offset = sum(
                func_t.keyword_args[j].typ.abi_type.embedded_static_size()
                for j in range(i)
            )
            calldata_offset = base_offset + static_offset
            _copy_from_calldata(ctx, ptr, calldata_offset, arg.typ)
        else:
            # Use default value
            default_node = func_t.default_values[arg.name]
            default_val = Expr(default_node, ctx).lower()
            if arg.typ._is_prim_word:
                ctx.builder.mstore(default_val, ptr)
            else:
                ctx.store_memory(default_val, ptr, arg.typ)


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
        is_ctor_context=is_ctor_context,
    )

    # Set up return handling
    pass_via_stack = codegen_ctx.pass_via_stack(func_t)
    returns_count = codegen_ctx.returns_stack_count(func_t)

    # Handle parameters
    # First: return buffer pointer if memory return
    if func_t.return_type is not None and returns_count == 0:
        codegen_ctx.return_buffer = builder.param()

    # Stack-passed args come as params
    for arg in func_t.arguments:
        if pass_via_stack[arg.name]:
            val = builder.param()
            ptr = codegen_ctx.new_variable(arg.name, arg.typ, mutable=False)
            builder.mstore(val, ptr)

    # Return PC is last param
    codegen_ctx.return_pc = builder.param()

    # Allocate return buffer if needed
    if func_t.return_type is not None:
        if returns_count > 0:
            codegen_ctx.return_buffer = codegen_ctx.new_internal_variable(
                func_t.return_type
            )

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
        module_ctx=module_t,
        builder=builder,
        func_t=func_t,
        is_ctor_context=True,
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
        builder.iload(IRLiteral(max(0, immutables_len - 32)))

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


def _register_constructor_args(
    ctx: VenomCodegenContext, func_t: ContractFunctionT
) -> None:
    """Register constructor args from DATA section."""
    # Constructor args are at offset 0 in the DATA section
    # (appended after deploy code)
    offset = 0

    for arg in func_t.positional_args:
        ptr = ctx.new_variable(arg.name, arg.typ, mutable=False)

        if arg.typ._is_prim_word:
            val = ctx.builder.dload(IRLiteral(offset))
            ctx.builder.mstore(val, ptr)
        else:
            size = arg.typ.memory_bytes_required
            ctx.builder.dloadbytes(IRLiteral(size), IRLiteral(offset), ptr)

        offset += arg.typ.abi_type.embedded_static_size()


def _generate_simple_deploy(
    builder: VenomBuilder,
    runtime_codesize: int,
    immutables_len: int,
) -> None:
    """Generate simple deploy code (no constructor)."""
    # Just emit the deploy epilogue
    _emit_deploy_epilogue(builder, runtime_codesize, immutables_len)


def _emit_deploy_epilogue(
    builder: VenomBuilder,
    runtime_codesize: int,
    immutables_len: int,
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
            # mcopy(size, src, dst) - src is 0 (immutables at start of memory)
            builder.mcopy(IRLiteral(immutables_len), IRLiteral(0), immutables_dst)
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
    builder.codecopy(
        IRLiteral(runtime_codesize),
        IRLabel("runtime_begin"),
        IRLiteral(DST_OFFSET),
    )

    # Return runtime + immutables
    total_size = builder.add(IRLiteral(runtime_codesize), IRLiteral(immutables_len))
    builder.return_(total_size, IRLiteral(DST_OFFSET))
