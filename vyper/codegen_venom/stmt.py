"""
Lower Vyper AST statements to Venom IR.

This module handles statement codegen: assignments, augmented assignments,
and other statement types. Complex multi-word assignments (structs, arrays)
are deferred to later tasks.
"""
from __future__ import annotations

from typing import Optional

from vyper import ast as vy_ast
from vyper.codegen.core import calculate_type_for_external_return
from vyper.codegen_venom.abi import abi_encode_to_buf
from vyper.codegen_venom.arithmetic import (
    safe_add,
    safe_div,
    safe_floordiv,
    safe_mod,
    safe_mul,
    safe_pow,
    safe_sub,
)
from vyper.exceptions import CompilerPanic, TypeCheckFailure
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import IntegerT
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.subscriptable import DArrayT, SArrayT, TupleT
from vyper.semantics.types.user import EventT, StructT
from vyper.utils import method_id_int
from vyper.venom.basicblock import IRLiteral, IROperand

from .buffer import Ptr
from .context import Constancy, VenomCodegenContext
from .expr import Expr
from .value import VyperValue


class Stmt:
    """Lower Vyper statements to Venom IR."""

    def __init__(self, node: vy_ast.VyperNode, ctx: VenomCodegenContext):
        self.node = node
        self.ctx = ctx
        self.builder = ctx.builder

    def lower(self) -> None:
        """Dispatch to type-specific lowering method."""
        fn_name = f"lower_{type(self.node).__name__}"
        method = getattr(self, fn_name, None)
        if method is None:
            raise CompilerPanic(f"Unsupported stmt: {type(self.node)}")
        return method()

    # === Assignment Statements ===

    def lower_AnnAssign(self) -> None:
        """Lower annotated assignment (variable declaration with init).

        Example: `x: uint256 = 5`

        Allocate local memory and store RHS into it.
        """
        node = self.node
        assert isinstance(node, vy_ast.AnnAssign)
        ltyp = node.target._metadata["type"]
        varname = node.target.id

        # AnnAssign always has a value in Vyper (semantic analysis ensures this)
        assert node.value is not None

        # Allocate memory for the new variable
        var = self.ctx.new_variable(varname, ltyp)

        rhs = Expr(node.value, self.ctx).lower()
        self._assign_value(var.value.ptr(), rhs, ltyp)

    def lower_Assign(self) -> None:
        """Lower regular assignment.

        Example: `x = 5` or `x[i] = 5` or `self.x = 5`

        For primitive types (single word), this is a simple store.
        For complex types (multi-word), uses temp buffer to handle potential overlap.

        IMPORTANT: RHS must be evaluated BEFORE LHS target pointer is computed.
        This ensures proper semantics for cases like `c[0] = c.pop()` where
        the RHS modifies the array length before the LHS bounds check.

        Reference: vyper/codegen/core.py:make_setter
        Reference: vyper/codegen/stmt.py:parse_Assign (for evaluation order)
        """
        node = self.node
        assert isinstance(node, vy_ast.Assign)
        # Get target info first (need it for tuple unpack decision)
        target = node.target
        target_typ = target._metadata["type"]

        # Handle tuple unpacking separately
        if isinstance(target, vy_ast.Tuple):
            return self._lower_tuple_unpack()

        # Special case: empty Bytestring assignment to storage/transient.
        if isinstance(target_typ, _BytestringT) and self._is_empty_value(node.value):
            dst_ptr = self._get_target_ptr(target)
            if dst_ptr.location == DataLocation.STORAGE:
                self.builder.sstore(dst_ptr.operand, IRLiteral(0))
                return
            elif dst_ptr.location == DataLocation.TRANSIENT:
                self.builder.tstore(dst_ptr.operand, IRLiteral(0))
                return

        # IMPORTANT: Evaluate RHS first, then compute LHS target pointer.
        # This matches legacy codegen and ensures proper semantics for cases
        # like `c[0] = c.pop()` where RHS modifies array length.
        src = Expr(node.value, self.ctx).lower()
        dst_ptr = self._get_target_ptr(target)
        self._assign_value(dst_ptr, src, target_typ)

    def _assign_value(self, dst_ptr: Ptr, src: VyperValue, typ) -> None:
        """Assign a VyperValue to a destination pointer.

        Handles both primitive word types (direct store) and complex types
        (with overlap-safe copying when source and dest are in the same
        address space).
        """
        if typ._is_prim_word:
            self.ctx.ptr_store(dst_ptr, self.ctx.unwrap(src))
        else:
            self._copy_complex_type(dst_ptr, src, typ)

    def _copy_complex_type(self, dst_ptr: Ptr, src_vv: VyperValue, typ) -> None:
        """Copy complex type into `dst_ptr`.

        Materializes `src_vv` to memory (via unwrap), then stages through a
        temporary buffer when source and destination are both in memory
        (potential aliasing).  When they are in different address spaces
        no aliasing is possible and the staging copy is skipped.
        """
        src_loc = src_vv.location  # None for stack values, else DataLocation
        src = self.ctx.unwrap(src_vv)  # always a memory ptr for complex types

        if src_loc is DataLocation.MEMORY and dst_ptr.location is DataLocation.MEMORY:
            # Both in memory — stage through temp for overlap safety.
            tmp_val = self.ctx.new_temporary_value(typ)
            self.ctx.copy_memory(tmp_val.operand, src, typ.memory_bytes_required)
            src = tmp_val.operand

        self._store_complex_type(dst_ptr, src, typ)

    def _store_complex_type(self, dst_ptr: Ptr, src: IROperand, typ) -> None:
        """Store complex value from memory `src` into `dst_ptr` (no overlap guard).

        Only called from `_copy_complex_type` which handles staging when needed.
        """
        if dst_ptr.location == DataLocation.STORAGE:
            # DynArray special case: only copy length + actual elements, not full capacity.
            # This matches legacy codegen behavior (core.py:_dynarray_make_setter).
            if isinstance(typ, DArrayT):
                self._copy_dynarray_to_storage(src, dst_ptr.operand, typ, transient=False)
            elif typ.storage_size_in_words == 1:
                val = self.builder.mload(src)
                self.builder.sstore(dst_ptr.operand, val)
            else:
                self.ctx.store_storage(src, dst_ptr.operand, typ)
        elif dst_ptr.location == DataLocation.TRANSIENT:
            # DynArray special case for transient storage
            if isinstance(typ, DArrayT):
                self._copy_dynarray_to_storage(src, dst_ptr.operand, typ, transient=True)
            elif typ.storage_size_in_words == 1:
                val = self.builder.mload(src)
                self.builder.tstore(dst_ptr.operand, val)
            else:
                self.ctx.store_transient(src, dst_ptr.operand, typ)
        elif dst_ptr.location == DataLocation.CODE:
            # Immutables in constructor - use ptr_store which handles GEP from immutables_alloca
            # For single-word types, load value from temp buffer first
            if typ.memory_bytes_required <= 32:
                val = self.builder.mload(src)
                self.ctx.ptr_store(dst_ptr, val)
            else:
                self.ctx.store_immutable(src, dst_ptr.operand, typ)
        else:
            self.ctx.copy_memory(dst_ptr.operand, src, typ.memory_bytes_required)

    def _lower_tuple_unpack(self) -> None:
        """Lower tuple unpacking assignment: a, b = expr.

        Key insight: Must load ALL values from source FIRST before assigning
        to any target. This handles cases like `a, b = b, a` correctly.

        Reference: vyper/codegen/stmt.py:_get_target (for tuple targets)
        Reference: vyper/codegen/core.py:make_setter (for multi handling)
        """
        node = self.node
        assert isinstance(node, vy_ast.Assign)
        assert isinstance(node.target, vy_ast.Tuple)
        target = node.target
        src = Expr(node.value, self.ctx).lower().operand

        # src is a pointer to the tuple in memory
        tuple_typ = target._metadata["type"]
        targets = target.elements

        # First pass: load all values from source tuple to temp variables.
        # This ensures correct semantics for overlapping cases like a,b = b,a.
        temp_vals = []
        offset = 0
        member_types = tuple_typ.member_types
        if isinstance(member_types, dict):
            member_types = member_types.values()
        for elem_typ in member_types:
            if offset == 0:
                elem_ptr = src
            elif isinstance(src, IRLiteral):
                elem_ptr = IRLiteral(src.value + offset)
            else:
                elem_ptr = self.builder.add(src, IRLiteral(offset))

            # Load the value
            val = self.ctx.load_memory(elem_ptr, elem_typ)
            temp_vals.append((val, elem_typ))

            offset += elem_typ.memory_bytes_required

        # Second pass: assign each loaded value to its target
        for (val, elem_typ), target_node in zip(temp_vals, targets):
            target_ptr = self._get_target_ptr(target_node)

            if elem_typ._is_prim_word:
                self.ctx.ptr_store(target_ptr, val)
            else:
                # Complex element type: val is a memory pointer
                if target_ptr.location == DataLocation.STORAGE:
                    # For single-word types, need to load value from memory
                    if elem_typ.storage_size_in_words == 1:
                        loaded_val = self.builder.mload(val)
                        self.builder.sstore(target_ptr.operand, loaded_val)
                    else:
                        self.ctx.store_storage(val, target_ptr.operand, elem_typ)
                elif target_ptr.location == DataLocation.TRANSIENT:
                    # For single-word types, need to load value from memory
                    if elem_typ.storage_size_in_words == 1:
                        loaded_val = self.builder.mload(val)
                        self.builder.tstore(target_ptr.operand, loaded_val)
                    else:
                        self.ctx.store_transient(val, target_ptr.operand, elem_typ)
                else:
                    self.ctx.copy_memory(target_ptr.operand, val, elem_typ.memory_bytes_required)

    def lower_AugAssign(self) -> None:
        """Lower augmented assignment.

        Example: `x += 5` or `self.x *= 2` or `self.arr[i] += 1`

        1. Load current value from target
        2. Apply binary operation
        3. Store result back to target

        Only supports primitive word types (no structs/arrays).
        """
        node = self.node
        assert isinstance(node, vy_ast.AugAssign)
        target = node.target
        target_typ = target._metadata["type"]
        op = node.op
        right_node = node.value

        # AugAssign only works on primitive word types
        if not target_typ._is_prim_word:
            raise TypeCheckFailure("AugAssign only valid for primitive types")

        # Get target pointer (with location info)
        dst_ptr = self._get_target_ptr(target)

        # Load current value
        left = self.ctx.ptr_load(dst_ptr)

        # Evaluate the RHS (AugAssign is always on primitives)
        right = Expr(right_node, self.ctx).lower_value()

        # Apply the operation
        result = self._apply_augassign_op(op, left, right, target_typ, right_node)

        # Store result back
        self.ctx.ptr_store(dst_ptr, result)

    # === Helper Methods ===

    def _copy_dynarray_to_storage(
        self, src: IROperand, dst_slot: IROperand, typ: DArrayT, transient: bool
    ) -> None:
        """Copy DynArray from memory to storage, writing only length + actual elements.

        This matches legacy codegen behavior (core.py:_dynarray_make_setter) which
        only copies the actual elements, not the full capacity. This is important
        for hevm symbolic equivalence - slots beyond length should not be modified.

        Args:
            src: Memory pointer to source DynArray
            dst_slot: Storage slot for destination
            typ: DynArray type
            transient: If True, use tstore instead of sstore
        """
        b = self.builder

        # Load length from source (at offset 0)
        length = b.mload(src)

        elem_typ = typ.value_type
        elem_words = elem_typ.storage_size_in_words

        # Create loop blocks
        cond_block = b.create_block("dyn_cond")
        body_block = b.create_block("dyn_body")
        exit_block = b.create_block("dyn_exit")

        # Entry: counter = 0, jump to cond
        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        # Condition: if counter >= length, goto exit, else body
        b.append_block(cond_block)
        b.set_block(cond_block)
        # done = counter >= length = iszero(lt(counter, length))
        done = b.iszero(b.lt(counter, length))
        cond_finish = b.current_block

        # Body: copy one element
        b.append_block(body_block)
        b.set_block(body_block)

        if elem_words == 1:
            # Simple case: each element is one storage word
            # src_offset = 32 + counter * 32
            src_offset = b.add(IRLiteral(32), b.mul(counter, IRLiteral(32)))
            src_ptr = b.add(src, src_offset)
            val = b.mload(src_ptr)

            # dst_slot_i = dst_slot + counter + 1 (skip length word)
            dst_slot_i = b.add(dst_slot, b.add(counter, IRLiteral(1)))
            if transient:
                b.tstore(dst_slot_i, val)
            else:
                b.sstore(dst_slot_i, val)
        else:
            # Complex case: element spans multiple words
            elem_mem_size = elem_typ.memory_bytes_required
            src_offset = b.add(IRLiteral(32), b.mul(counter, IRLiteral(elem_mem_size)))
            src_ptr = b.add(src, src_offset)

            # dst_slot_i = dst_slot + 1 + counter * elem_words
            dst_slot_i = b.add(dst_slot, b.add(IRLiteral(1), b.mul(counter, IRLiteral(elem_words))))
            if transient:
                self.ctx.store_transient(src_ptr, dst_slot_i, elem_typ)
            else:
                self.ctx.store_storage(src_ptr, dst_slot_i, elem_typ)

        # Increment counter and loop
        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        # Wire up conditional jump (done after body to have block refs)
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block: write length last (matches legacy behavior)
        b.append_block(exit_block)
        b.set_block(exit_block)
        if transient:
            b.tstore(dst_slot, length)
        else:
            b.sstore(dst_slot, length)

    def _is_empty_value(self, node: vy_ast.VyperNode) -> bool:
        """Check if AST node represents an empty DynArray/Bytestring value.

        Matches legacy codegen's is_empty_intrinsic property.
        Returns True for: [], b"", empty(DynArray[...]), empty(Bytes[...])
        """
        # Empty list literal: []
        if isinstance(node, vy_ast.List) and len(node.elements) == 0:
            return True

        # Empty bytes literal: b""
        if isinstance(node, vy_ast.Bytes) and len(node.value) == 0:
            return True

        # empty() builtin call
        if isinstance(node, vy_ast.Call):
            if isinstance(node.func, vy_ast.Name) and node.func.id == "empty":
                return True

        return False

    def _get_target_ptr(self, target: vy_ast.VyperNode) -> Ptr:
        """Get pointer to assignment target.

        Handles:
        - Name: local variable (memory)
        - Subscript: array/mapping access (memory or storage)
        - Attribute: struct field or state variable (self.x)

        Returns Ptr with location info for dispatch.
        """
        if isinstance(target, vy_ast.Name):
            varname = target.id

            # Check if it's a local variable
            if varname in self.ctx.variables:
                return self.ctx.variables[varname].value.ptr()

            # Check if it's an immutable assignment in constructor
            varinfo = target._expr_info.var_info
            if varinfo is not None and varinfo.is_immutable and self.ctx.is_ctor_context:
                return Ptr(IRLiteral(varinfo.position.position), DataLocation.CODE)

            raise CompilerPanic(f"Unknown variable: {varname}")

        elif isinstance(target, vy_ast.Attribute):
            # self.x = ... (state variable assignment)
            varinfo = target._expr_info.var_info

            if varinfo is not None:
                # Storage/transient variable - use actual location from varinfo
                if not varinfo.is_constant and not varinfo.is_immutable:
                    return Ptr(IRLiteral(varinfo.position.position), varinfo.location)

                # Immutable in constructor context
                if varinfo.is_immutable and self.ctx.is_ctor_context:
                    return Ptr(IRLiteral(varinfo.position.position), DataLocation.CODE)

                if varinfo.is_constant:
                    raise TypeCheckFailure("Cannot assign to constant")
                if varinfo.is_immutable:
                    raise TypeCheckFailure("Cannot assign to immutable outside constructor")

            # Struct field access (point.x = ...)
            sub_typ = target.value._metadata.get("type")
            if isinstance(sub_typ, StructT) and target.attr in sub_typ.member_types:
                # Use Expr to compute the field pointer
                return Expr(target, self.ctx).lower().ptr()

            raise CompilerPanic(f"Unsupported attribute target: {target.attr}")

        elif isinstance(target, vy_ast.Subscript):
            # x[i] = ... or self.arr[i] = ... or self.map[key] = ...
            # Use Expr to compute the element pointer/slot
            return Expr(target, self.ctx).lower().ptr()

        raise CompilerPanic(f"Unsupported assignment target: {type(target)}")

    def _apply_augassign_op(
        self,
        op: vy_ast.VyperNode,
        left: IROperand,
        right: IROperand,
        typ,
        right_node: vy_ast.VyperNode,
    ) -> IROperand:
        """Apply augmented assignment operation.

        Reuses arithmetic/bitwise logic from Expr class.
        """
        # Bitwise operations - no overflow checks
        if isinstance(op, vy_ast.BitAnd):
            return self.builder.and_(left, right)
        if isinstance(op, vy_ast.BitOr):
            return self.builder.or_(left, right)
        if isinstance(op, vy_ast.BitXor):
            return self.builder.xor(left, right)

        # Shift operations
        if isinstance(op, vy_ast.LShift):
            return self.builder.shl(right, left)
        if isinstance(op, vy_ast.RShift):
            if isinstance(typ, IntegerT) and typ.is_signed:
                return self.builder.sar(right, left)
            return self.builder.shr(right, left)

        # Arithmetic operations with overflow checks
        if isinstance(op, vy_ast.Add):
            return self._safe_add(left, right, typ)
        if isinstance(op, vy_ast.Sub):
            return self._safe_sub(left, right, typ)
        if isinstance(op, vy_ast.Mult):
            return self._safe_mul(left, right, typ)
        if isinstance(op, vy_ast.Div):
            return self._safe_div(left, right, typ)
        if isinstance(op, vy_ast.FloorDiv):
            return self._safe_floordiv(left, right, typ)
        if isinstance(op, vy_ast.Mod):
            return self._safe_mod(left, right, typ)
        if isinstance(op, vy_ast.Pow):
            return self._safe_pow(left, right, typ, right_node)

        raise CompilerPanic(f"Unsupported AugAssign op: {type(op)}")

    # === Safe Arithmetic Operations ===
    # Delegating to arithmetic.py module functions

    def _safe_add(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Add with overflow checking."""
        return safe_add(self.builder, x, y, typ)

    def _safe_sub(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Subtract with overflow checking."""
        return safe_sub(self.builder, x, y, typ)

    def _safe_mul(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Multiply with overflow checking."""
        return safe_mul(self.builder, x, y, typ)

    def _safe_div(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Decimal division with overflow checking."""
        return safe_div(self.builder, x, y, typ)

    def _safe_floordiv(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Integer floor division with overflow checking."""
        return safe_floordiv(self.builder, x, y, typ)

    def _safe_mod(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Modulo with divisor check."""
        return safe_mod(self.builder, x, y, typ)

    def _safe_pow(self, x: IROperand, y: IROperand, typ, right_node: vy_ast.VyperNode) -> IROperand:
        """Exponentiation - only with literal exponent for bounds checking."""
        # For AugAssign, we require a literal exponent for bounds check
        right_reduced = right_node.reduced()
        if not isinstance(right_reduced, vy_ast.Int):
            raise TypeCheckFailure("AugAssign pow requires literal exponent")

        exp_literal = right_reduced.value
        return safe_pow(self.builder, x, y, typ, base_literal=None, exp_literal=exp_literal)

    # === Control Flow Statements ===

    def lower_If(self) -> None:
        """Lower if/elif/else statement."""
        node = self.node
        assert isinstance(node, vy_ast.If)

        # Evaluate condition in current block (bool is a primitive)
        cond = Expr(node.test, self.ctx).lower_value()
        cond_block = self.builder.current_block

        # Create blocks
        then_block = self.builder.create_block("then")
        else_block = self.builder.create_block("else")

        # Process then branch
        self.builder.append_block(then_block)
        self.builder.set_block(then_block)
        self._lower_body(node.body)
        then_block_finish = self.builder.current_block

        # Process else branch
        self.builder.append_block(else_block)
        self.builder.set_block(else_block)
        if node.orelse:
            self._lower_body(node.orelse)  # handles elif via recursive If
        else_block_finish = self.builder.current_block

        # Add conditional jump to cond_block (AFTER processing branches)
        cond_block.append_instruction("jnz", cond, then_block.label, else_block.label)

        # Create exit/merge block only if at least one branch needs it
        then_needs_exit = not then_block_finish.is_terminated
        else_needs_exit = not else_block_finish.is_terminated

        if then_needs_exit or else_needs_exit:
            exit_block = self.builder.create_block("if_exit")
            self.builder.append_block(exit_block)
            self.builder.set_block(exit_block)

            if then_needs_exit:
                then_block_finish.append_instruction("jmp", exit_block.label)
            if else_needs_exit:
                else_block_finish.append_instruction("jmp", exit_block.label)

    def _lower_body(self, stmts: list) -> None:
        """Lower a list of statements."""
        for stmt in stmts:
            # Skip dead code after terminating statements (continue, break, return, raise)
            if self.builder.is_terminated():
                break
            Stmt(stmt, self.ctx).lower()

    # === For Loop Statements ===

    def lower_For(self) -> None:
        """Lower for loop - dispatches to range or iter loop."""
        node = self.node
        assert isinstance(node, vy_ast.For)
        if self._is_range_call(node.iter):
            self._lower_range_loop(node)
        else:
            self._lower_iter_loop(node)

    def _is_range_call(self, node) -> bool:
        """Check if node is a range() call."""
        return isinstance(node, vy_ast.Call) and node.get("func.id") == "range"

    def _lower_range_loop(self, node: vy_ast.For) -> None:
        """Lower for i in range(n) or range(start, end).

        Creates 5-block CFG structure:
        - entry: initialize counter, bound check, compute end
        - cond: check counter != end
        - body: store counter to user var, execute body
        - incr: increment counter
        - exit: continue after loop
        """
        # Get loop variable info
        assert isinstance(node.target, vy_ast.AnnAssign)
        target_type = node.target.target._metadata["type"]
        varname = node.target.target.id

        # Parse range arguments
        range_call = node.iter
        assert isinstance(range_call, vy_ast.Call)
        args = range_call.args

        # Evaluate range arguments in range_scope (treats context as constant
        # to prevent state-modifying operations)
        start: IROperand
        rounds: IROperand
        with self.ctx.range_scope():
            if len(args) == 1:
                start = IRLiteral(0)
                end_expr = Expr(args[0], self.ctx).lower_value()
            else:
                start = Expr(args[0], self.ctx).lower_value()
                end_expr = Expr(args[1], self.ctx).lower_value()

            # Handle bound kwarg for dynamic ranges
            kwargs = {kw.arg: kw.value for kw in range_call.keywords}
            has_bound = "bound" in kwargs

            if has_bound:
                # Dynamic range: compute rounds = end - start
                # The bound check will catch if rounds > bound (including negative/underflow)
                bound_node = kwargs["bound"]
                # Handle both literal Int and constant Name (e.g., bound=MAX_SIZE)
                if bound_node.has_folded_value:
                    bound_node = bound_node.get_folded_value()
                rounds_bound = bound_node.value
                rounds = self.builder.sub(end_expr, start)
            else:
                # Static range: start and end must be literals
                if isinstance(start, IRLiteral) and isinstance(end_expr, IRLiteral):
                    rounds = IRLiteral(end_expr.value - start.value)
                    rounds_bound = rounds.value
                else:
                    # Non-literal but no bound - semantic analysis should catch this
                    raise CompilerPanic("range() with non-literal args requires bound=")

        # Allocate counter variable in memory for user access
        counter_local = self.ctx.new_variable(varname, target_type, mutable=False)
        self.ctx.forvars[varname] = True

        # Create blocks
        entry_block = self.builder.create_block("for_entry")
        cond_block = self.builder.create_block("for_cond")
        body_block = self.builder.create_block("for_body")
        incr_block = self.builder.create_block("for_incr")
        exit_block = self.builder.create_block("for_exit")

        # Jump to entry from current block
        self.builder.jmp(entry_block.label)

        # Entry block: initialize counter, check bound
        self.builder.append_block(entry_block)
        self.builder.set_block(entry_block)
        counter_var = self.builder.assign(start)

        # Bound checks for dynamic ranges
        if has_bound:
            # Check start <= end (prevents underflow in rounds computation)
            is_signed = target_type.is_signed
            if is_signed:
                invalid_order = self.builder.sgt(start, end_expr)
            else:
                invalid_order = self.builder.gt(start, end_expr)
            valid_order = self.builder.iszero(invalid_order)
            self.builder.assert_(valid_order)

            # Check rounds <= rounds_bound
            invalid = self.builder.gt(rounds, IRLiteral(rounds_bound))
            valid = self.builder.iszero(invalid)
            self.builder.assert_(valid)

        # Compute end value: end = start + rounds
        end_val = self.builder.add(start, rounds)
        self.builder.jmp(cond_block.label)

        # Condition block: check if counter == end
        self.builder.append_block(cond_block)
        self.builder.set_block(cond_block)
        done = self.builder.eq(counter_var, end_val)
        cond_finish = self.builder.current_block

        # Set up loop targets for break/continue using context manager
        with self.ctx.loop_scope(exit_block.label, incr_block.label):
            # Body block: store counter to user var, execute body
            self.builder.append_block(body_block)
            self.builder.set_block(body_block)
            self.ctx.ptr_store(counter_local.value.ptr(), counter_var)
            self._lower_body(node.body)
            body_finish = self.builder.current_block
            if not body_finish.is_terminated:
                body_finish.append_instruction("jmp", incr_block.label)

        # Increment block
        self.builder.append_block(incr_block)
        self.builder.set_block(incr_block)
        new_counter = self.builder.add(counter_var, IRLiteral(1))
        # Update counter_var to new value for next iteration
        self.builder.assign_to(new_counter, counter_var)
        self.builder.jmp(cond_block.label)

        # Add conditional jump to cond block (after body is processed)
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        self.builder.append_block(exit_block)
        self.builder.set_block(exit_block)

        # Cleanup
        del self.ctx.forvars[varname]

    def _lower_iter_loop(self, node: vy_ast.For) -> None:
        """Lower for item in array.

        Creates 5-block CFG structure similar to range loop but:
        - Iterates over array elements
        - Copies element to loop variable each iteration
        """
        # Get loop variable info
        assert isinstance(node.target, vy_ast.AnnAssign)
        target_type = node.target.target._metadata["type"]
        varname = node.target.target.id

        # Evaluate array expression in range_scope (treats context as constant
        # to prevent state-modifying operations)
        with self.ctx.range_scope():
            array_vv = Expr(node.iter, self.ctx).lower()
        array = array_vv.operand
        array_typ = node.iter._metadata["type"]
        location = array_vv.location or node.iter._expr_info.location

        # If array is a stack value (e.g., from ternary expression), the operand
        # is a pointer to memory. Use MEMORY as the location.
        if location == DataLocation.UNSET:
            location = DataLocation.MEMORY

        # Determine word scale based on location
        # Storage/Transient: 1 slot per word, Memory: 32 bytes per word
        is_slot_addressed = location in (DataLocation.STORAGE, DataLocation.TRANSIENT)
        word_scale = 1 if is_slot_addressed else 32

        # Get length and bound
        length: IROperand
        if isinstance(array_typ, DArrayT):
            # Dynamic array: length is first word
            length = self.builder.load(array, location)
            bound = array_typ.count
        elif isinstance(array_typ, SArrayT):
            # Static array: length is compile-time constant
            length = IRLiteral(array_typ.count)
            bound = array_typ.count
        else:
            raise CompilerPanic(f"Cannot iterate over type: {array_typ}")

        # Element size (in slots for storage, bytes for memory)
        elem_size = array_typ.value_type.get_size_in(location)

        # Allocate loop variable (copy of element, not reference)
        item_local = self.ctx.new_variable(varname, target_type, mutable=False)
        self.ctx.forvars[varname] = True

        # Create blocks
        entry_block = self.builder.create_block("iter_entry")
        cond_block = self.builder.create_block("iter_cond")
        body_block = self.builder.create_block("iter_body")
        incr_block = self.builder.create_block("iter_incr")
        exit_block = self.builder.create_block("iter_exit")

        # Jump to entry
        self.builder.jmp(entry_block.label)

        # Entry block: initialize index, bound check
        self.builder.append_block(entry_block)
        self.builder.set_block(entry_block)
        index_var = self.builder.assign(IRLiteral(0))

        # Bound check for dynamic arrays: assert length <= bound
        if isinstance(array_typ, DArrayT):
            invalid = self.builder.gt(length, IRLiteral(bound))
            valid = self.builder.iszero(invalid)
            self.builder.assert_(valid)

        self.builder.jmp(cond_block.label)

        # Condition block: check if index == length
        self.builder.append_block(cond_block)
        self.builder.set_block(cond_block)
        done = self.builder.eq(index_var, length)
        cond_finish = self.builder.current_block

        # Set up loop targets
        with self.ctx.loop_scope(exit_block.label, incr_block.label):
            # Body block: compute element address, copy to loop var
            self.builder.append_block(body_block)
            self.builder.set_block(body_block)

            # Compute element address
            # elem_addr = array + offset + index * elem_size
            # For DArrayT, offset = word_scale (skip length word/slot)
            # For SArrayT, offset = 0
            offset_base = word_scale if isinstance(array_typ, DArrayT) else 0
            index_offset = self.builder.mul(index_var, IRLiteral(elem_size))
            if offset_base > 0:
                total_offset = self.builder.add(IRLiteral(offset_base), index_offset)
            else:
                total_offset = index_offset
            elem_addr = self.builder.add(array, total_offset)

            # Copy element to loop variable (always in memory)
            if is_slot_addressed:
                if elem_size == 1:
                    # Single slot: load from storage/transient, mstore to memory
                    val = self.builder.load(elem_addr, location)
                    self.builder.mstore(item_local.value.operand, val)
                else:
                    # Multi-slot: use generic helper that dispatches on location
                    self.ctx.slot_to_memory(
                        elem_addr, item_local.value.operand, elem_size, location
                    )
            else:
                if elem_size <= 32:
                    # Single word: load dispatches on location (mload/calldataload/dload)
                    val = self.builder.load(elem_addr, location)
                    self.builder.mstore(item_local.value.operand, val)
                else:
                    # Multi-word: use context helper which handles pre-Cancun
                    self.ctx.copy_memory(item_local.value.operand, elem_addr, elem_size)

            self._lower_body(node.body)
            body_finish = self.builder.current_block
            if not body_finish.is_terminated:
                body_finish.append_instruction("jmp", incr_block.label)

        # Increment block
        self.builder.append_block(incr_block)
        self.builder.set_block(incr_block)
        new_index = self.builder.add(index_var, IRLiteral(1))
        self.builder.assign_to(new_index, index_var)
        self.builder.jmp(cond_block.label)

        # Add conditional jump
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        self.builder.append_block(exit_block)
        self.builder.set_block(exit_block)

        # Cleanup
        del self.ctx.forvars[varname]

    def lower_Break(self) -> None:
        """Lower break statement - jump to loop exit."""
        if self.ctx.break_target is None:
            raise CompilerPanic("break outside loop")
        self.builder.jmp(self.ctx.break_target)

    def lower_Continue(self) -> None:
        """Lower continue statement - jump to loop increment."""
        if self.ctx.continue_target is None:
            raise CompilerPanic("continue outside loop")
        self.builder.jmp(self.ctx.continue_target)

    def lower_Pass(self) -> None:
        """Lower pass statement - no-op."""
        pass

    def lower_Expr(self) -> None:
        """Lower expression statement (e.g., function call with no return value)."""
        node = self.node
        assert isinstance(node, vy_ast.Expr)
        # Evaluate the expression for its side effects
        Expr(node.value, self.ctx).lower()

    def lower_Return(self) -> None:
        """Lower return statement.

        Dispatches to internal or external return handling.
        """
        node = self.node
        assert isinstance(node, vy_ast.Return)
        func_t = self.ctx.func_t

        if func_t is None:
            raise CompilerPanic("Return outside function")

        # Evaluate return value if present
        ret_val: Optional[IROperand] = None
        if node.value is not None:
            # lower_value() handles all locations (storage, memory, code)
            # and returns a usable value (loaded for primitives, memory ptr for complex)
            ret_val = Expr(node.value, self.ctx).lower_value()

        # Dispatch: internal vs external
        if self.ctx.return_pc is not None:
            self._lower_internal_return(ret_val, func_t)
        else:
            self._lower_external_return(ret_val, func_t)

    def _lower_internal_return(
        self, ret_val: Optional[IROperand], func_t: ContractFunctionT
    ) -> None:
        """Lower internal function return.

        For internal functions:
        - Load return values and pass on stack
        - ret to return_pc
        """
        return_pc = self.ctx.return_pc
        assert return_pc is not None  # Caller ensures this

        if ret_val is None:
            self.builder.ret(return_pc)
            return

        returns_count = self.ctx.returns_stack_count(func_t)
        ret_typ = func_t.return_type
        assert ret_typ is not None

        if returns_count > 0:
            # Stack return - load values and pass to ret
            ret_vals: list[IROperand] = []

            if hasattr(ret_typ, "tuple_items"):
                # Tuple/struct return - load each element from memory pointer
                # This handles both multi-element tuples AND single-element structs
                for i, (_k, _elem_t) in enumerate(ret_typ.tuple_items()):
                    if i == 0:
                        src_ptr = ret_val
                    elif isinstance(ret_val, IRLiteral):
                        src_ptr = IRLiteral(ret_val.value + i * 32)
                    else:
                        src_ptr = self.builder.add(ret_val, IRLiteral(i * 32))
                    ret_vals.append(self.builder.mload(src_ptr))
            else:
                # Primitive single value - just use directly
                ret_vals.append(ret_val)

            self.builder.ret(*ret_vals, return_pc)

        elif self.ctx.return_buffer is not None:
            # Memory return - store to buffer, caller reads it
            self.ctx.store_memory(ret_val, self.ctx.return_buffer, ret_typ)
            self.builder.ret(return_pc)

        else:
            raise CompilerPanic("Internal function missing return mechanism")

    def _lower_external_return(
        self, ret_val: Optional[IROperand], func_t: ContractFunctionT
    ) -> None:
        """Lower external function return.

        For external functions:
        1. Nonreentrant unlock (if applicable)
        2. ABI encode the return value (if any), unless @raw_return
        3. Return encoded data or stop
        """
        # Nonreentrant unlock
        self.ctx.emit_nonreentrant_unlock(func_t)

        # Void return
        if ret_val is None:
            self.builder.stop()
            return

        ret_typ = func_t.return_type
        assert ret_typ is not None

        # Raw return: return bytes directly without ABI encoding
        # The @raw_return decorator bypasses ABI encoding for proxy patterns
        if func_t.do_raw_return:
            # ret_val is a pointer to [length (32 bytes)][data...]
            # Copy to a fresh buffer to ensure it's in memory
            buf_val = self.ctx.new_temporary_value(ret_typ)
            self.ctx.store_memory(ret_val, buf_val.operand, ret_typ)

            # Get length from first 32 bytes
            return_len = self.builder.mload(buf_val.operand)
            # Data starts at buf + 32
            return_offset = self.builder.add(buf_val.operand, IRLiteral(32))
            self.builder.return_(return_offset, return_len)
            return

        # Valued return - ABI encode
        # Optimization: single word types don't need full encoding
        if ret_typ._is_prim_word:
            buf_val = self.ctx.new_temporary_value(ret_typ)
            self.ctx.ptr_store(buf_val.ptr(), ret_val)
            self.builder.return_(buf_val.operand, IRLiteral(32))
            return

        # Calculate max return size
        # For ABI conformance, single-element returns are wrapped in a tuple
        # This is what provides the offset pointer for dynamic types
        external_return_type = calculate_type_for_external_return(ret_typ)
        maxlen = external_return_type.abi_type.size_bound()

        # Allocate return buffer
        buf = self.ctx.allocate_buffer(maxlen)

        # ABI encode to buffer
        # Use external_return_type (wrapped in tuple) for proper ABI encoding
        encoded_len = abi_encode_to_buf(self.ctx, buf._ptr, ret_val, external_return_type)

        # Return encoded data
        self.builder.return_(buf._ptr, encoded_len)

    # === Event Logging ===

    def lower_Log(self) -> None:
        """Lower log statement (event emission).

        Events in Vyper are emitted via LOG0-LOG4 opcodes:
        - topic0: Always event signature hash (keccak256 of signature)
        - topic1-3: Indexed parameters (up to 3)
        - data: Non-indexed parameters, ABI-encoded

        Source: vyper/codegen/stmt.py:parse_Log and vyper/codegen/events.py
        """
        node = self.node
        assert isinstance(node, vy_ast.Log)
        event: EventT = node._metadata["type"]

        # Get arguments - can be keyword or positional
        call_node = node.value
        if len(call_node.keywords) > 0:
            arg_nodes = [arg.value for arg in call_node.keywords]
        else:
            arg_nodes = call_node.args

        # Lower all argument expressions
        # lower_value() handles storage/code -> memory copy for complex types
        args = []
        for arg in arg_nodes:
            arg_typ = arg._metadata["type"]
            args.append((Expr(arg, self.ctx).lower_value(), arg_typ))

        # Split into indexed (topics) and non-indexed (data)
        topic_vals = []
        data_vals = []
        data_typs = []

        for (arg_val, arg_typ), is_indexed in zip(args, event.indexed):
            if is_indexed:
                topic_vals.append((arg_val, arg_typ))
            else:
                data_vals.append(arg_val)
                data_typs.append(arg_typ)

        # Build topics list - starts with event signature hash
        topics: list[IROperand] = [IRLiteral(event.event_id)]

        for val, typ in topic_vals:
            topic = self._encode_log_topic(val, typ)
            topics.append(topic)

        # Encode non-indexed data to buffer
        abi_buf_ptr: IROperand
        encoded_len: IROperand
        if data_vals:
            # Create a tuple type from the data types
            tuple_typ = TupleT(tuple(data_typs))
            bufsz = tuple_typ.abi_type.size_bound()

            # Allocate buffer for tuple data in memory
            data_buf = self.ctx.allocate_buffer(tuple_typ.memory_bytes_required)

            # Store each data value into the tuple buffer
            offset = 0
            for val, typ in zip(data_vals, data_typs):
                if offset == 0:
                    dst = data_buf._ptr
                else:
                    dst = self.builder.add(data_buf._ptr, IRLiteral(offset))
                self.ctx.store_memory(val, dst, typ)
                offset += typ.memory_bytes_required

            # Allocate ABI encoding output buffer
            abi_buf = self.ctx.allocate_buffer(bufsz)
            abi_buf_ptr = abi_buf._ptr

            # ABI encode the tuple
            encoded_len = abi_encode_to_buf(self.ctx, abi_buf_ptr, data_buf._ptr, tuple_typ)
        else:
            # No data - use zero size
            abi_buf_ptr = IRLiteral(0)
            encoded_len = IRLiteral(0)

        # Emit log instruction
        assert len(topics) <= 4, "too many topics"

        self.builder.log(len(topics), abi_buf_ptr, encoded_len, *topics)

    def _encode_log_topic(self, val: IROperand, typ) -> IROperand:
        """Encode a single indexed topic value.

        Per Solidity ABI spec for indexed event encoding:
        - Primitive word types (uint, int, address, bool, bytesN): use directly
        - bytes/string: keccak256 hash of contents

        Source: vyper/codegen/events.py:_encode_log_topics
        """
        if typ._is_prim_word:
            # Primitive word type - use value directly
            # If val is a memory pointer (for complex paths), we need to load it
            # But in practice, indexed args are primitive words computed as values
            return val

        elif isinstance(typ, _BytestringT):
            # bytes/string - must be keccak256 hashed per ABI spec
            # val is a pointer to [length][data]
            data_ptr = self.builder.add(val, IRLiteral(32))
            length = self.builder.mload(val)
            return self.builder.sha3(data_ptr, length)

        else:
            raise CompilerPanic(f"Event indexes may only be value types, got {typ}")

    # === Error Handling (Assert/Raise) ===

    def lower_Assert(self) -> None:
        """Lower assert statement.

        Handles three cases:
        1. Simple assert (no msg): jnz cond, ok, fail; fail: revert 0,0; ok: continue
        2. UNREACHABLE: jnz cond, ok, fail; fail: invalid; ok: continue
        3. With reason string: encode Error(string) and revert

        Source: vyper/codegen/stmt.py:parse_Assert, _assert_reason
        """
        node = self.node
        assert isinstance(node, vy_ast.Assert)
        cond = Expr(node.test, self.ctx).lower_value()

        if node.msg:
            self._assert_with_reason(cond, node.msg)
        else:
            # Simple assert - revert with no data on failure
            ok_block = self.builder.create_block("assert_ok")
            fail_block = self.builder.create_block("assert_fail")

            self.builder.jnz(cond, ok_block.label, fail_block.label)

            # Fail block: revert 0, 0
            self.builder.append_block(fail_block)
            self.builder.set_block(fail_block)
            with self.builder.error_context("user assert"):
                self.builder.revert(IRLiteral(0), IRLiteral(0))

            # Ok block: continue
            self.builder.append_block(ok_block)
            self.builder.set_block(ok_block)

    def lower_Raise(self) -> None:
        """Lower raise statement.

        Handles three cases:
        1. Bare raise: revert 0, 0
        2. UNREACHABLE: invalid
        3. With reason: encode Error(string) and revert

        Source: vyper/codegen/stmt.py:parse_Raise
        """
        node = self.node
        assert isinstance(node, vy_ast.Raise)

        if node.exc is None:
            # Bare raise: revert 0, 0
            with self.builder.error_context("user raise"):
                self.builder.revert(IRLiteral(0), IRLiteral(0))
        elif isinstance(node.exc, vy_ast.Name) and node.exc.id == "UNREACHABLE":
            # UNREACHABLE: invalid opcode
            with self.builder.error_context("raise unreachable"):
                self.builder.invalid()
        else:
            # Raise with reason string
            self._revert_with_reason(node.exc)

    def _assert_with_reason(self, cond: IROperand, msg: vy_ast.VyperNode) -> None:
        """Handle assert with reason (including UNREACHABLE).

        Source: vyper/codegen/stmt.py:_assert_reason
        """
        if isinstance(msg, vy_ast.Name) and msg.id == "UNREACHABLE":
            # UNREACHABLE: use invalid opcode on failure
            ok_block = self.builder.create_block("assert_ok")
            fail_block = self.builder.create_block("assert_fail")

            self.builder.jnz(cond, ok_block.label, fail_block.label)

            # Fail block: invalid
            self.builder.append_block(fail_block)
            self.builder.set_block(fail_block)
            with self.builder.error_context("assert unreachable"):
                self.builder.invalid()

            # Ok block: continue
            self.builder.append_block(ok_block)
            self.builder.set_block(ok_block)
        else:
            # Assert with reason string - revert with Error(string) on failure
            ok_block = self.builder.create_block("assert_ok")
            fail_block = self.builder.create_block("assert_fail")

            self.builder.jnz(cond, ok_block.label, fail_block.label)

            # Fail block: revert with reason
            self.builder.append_block(fail_block)
            self.builder.set_block(fail_block)
            self._revert_with_reason(msg)

            # Ok block: continue
            self.builder.append_block(ok_block)
            self.builder.set_block(ok_block)

    def _revert_with_reason(self, msg: vy_ast.VyperNode) -> None:
        """Emit revert with Error(string) encoding.

        Error(string) selector: 0x08c379a0
        Buffer layout:
        - buf+0: selector (left-padded in 32-byte word)
        - buf+32: ABI-encoded (string,) tuple
        Final revert: from buf+28 with length 4 + encoded_len

        Source: vyper/codegen/stmt.py:_assert_reason
        """
        # Evaluate message in constant context (prevent state changes)
        old_constancy = self.ctx.constancy
        try:
            self.ctx.constancy = Constancy.Constant
            msg_vv = Expr(msg, self.ctx).lower()
            msg_val = self.ctx.unwrap(msg_vv)  # Copies storage/transient to memory
        finally:
            self.ctx.constancy = old_constancy

        msg_typ = msg._metadata["type"]

        # Wrap message as tuple for ABI encoding (matches wrap_value_for_external_return)
        # Error(string) expects the string to be encoded as a tuple element
        wrapped_typ = TupleT((msg_typ,))

        # Buffer size: 64 (selector word + offset word minimum) + message data
        bufsz = 64 + msg_typ.memory_bytes_required

        # Allocate buffer
        buf = self.ctx.allocate_buffer(bufsz)

        # Error(string) selector
        selector = method_id_int("Error(string)")

        # Store selector at buf (left-padded in 32-byte word)
        self.builder.mstore(buf._ptr, IRLiteral(selector))

        # Payload buffer starts at buf + 32
        payload_buf = self.builder.add(buf._ptr, IRLiteral(32))

        # msg_val is a pointer to the string in memory
        # We need to store it at a location so we can encode the tuple
        # For a tuple (string,), we store the string pointer, then encode
        tuple_buf = self.ctx.allocate_buffer(wrapped_typ.memory_bytes_required)
        self.ctx.store_memory(msg_val, tuple_buf._ptr, msg_typ)

        # ABI encode the wrapped message to payload buffer
        encoded_len = abi_encode_to_buf(self.ctx, payload_buf, tuple_buf._ptr, wrapped_typ)

        # Revert from buf+28 (so selector is at bytes 0-3) with length 4 + encoded_len
        revert_offset = self.builder.add(buf._ptr, IRLiteral(28))
        revert_len = self.builder.add(IRLiteral(4), encoded_len)
        with self.builder.error_context("user revert with reason"):
            self.builder.revert(revert_offset, revert_len)
