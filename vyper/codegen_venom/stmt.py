"""
Lower Vyper AST statements to Venom IR.

This module handles statement codegen: assignments, augmented assignments,
and other statement types. Complex multi-word assignments (structs, arrays)
are deferred to later tasks.
"""

from __future__ import annotations

from typing import Optional

from vyper import ast as vy_ast
from vyper.codegen.core import calculate_type_for_external_return, has_length_word
from vyper.codegen_venom.abi import (
    abi_encode_to_buf,
    abi_encode_values_to_buf,
    runtime_abi_size_for_encode,
)
from vyper.codegen_venom.arithmetic import apply_binop
from vyper.exceptions import CodegenPanic, CompilerPanic, TypeCheckFailure, tag_exceptions
from vyper.semantics.analysis.utils import get_expr_writes
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import (
    VyperType,
    _BytestringT,
    is_bounded_length,
    is_unbounded_bytestring_type,
    is_unbounded_dynarray_type,
    is_unbounded_sequence_type,
    type_contains_unbounded_sequence,
)
from vyper.semantics.types.function import ContractFunctionT, StateMutability
from vyper.semantics.types.subscriptable import DArrayT, SArrayT, TupleT
from vyper.semantics.types.user import ErrorT, EventT, StructT
from vyper.utils import method_id_int
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

from .buffer import Ptr
from .builtins.simple import _get_empty_type
from .calling_convention import returns_dynamic_count, returns_stack_count
from .context import Constancy, LocalVariable, VenomCodegenContext
from .eval_order import later_expressions_can_mutate_memory_or_storage
from .expr import Expr
from .value import VyperValue


def _referenced_variables(node: vy_ast.VyperNode) -> set:
    """Return variables read while evaluating an expression."""
    node = node.reduced()
    ret: set = set()
    if isinstance(node, vy_ast.ExprNode) and node._expr_info is not None:
        ret.update(access.variable for access in node._expr_info._reads)
    for child in node._children:
        ret |= _referenced_variables(child)
    return ret


def _contains_writeable_call(node: vy_ast.VyperNode) -> bool:
    if _emits_writeable_call(node):
        return True

    functions = set()
    for func_t in _called_internal_functions(node):
        functions.add(func_t)
        functions.update(func_t.reachable_internal_functions)
    return any(_emits_writeable_call(func_t.decl_node) for func_t in functions)


def _called_internal_functions(node: vy_ast.VyperNode) -> set:
    ret = set()
    for call in node.get_descendants(vy_ast.Call, include_self=True):
        func_t = call.func._metadata.get("type")
        if isinstance(func_t, ContractFunctionT) and (func_t.is_internal or func_t.is_constructor):
            ret.add(func_t.get_concrete_override())
    return ret


def _emits_writeable_call(node: vy_ast.VyperNode) -> bool:
    # Delayed import avoids a cycle through the builtin registry.
    from vyper.builtins.functions import RawCall, Send, _CreateBase

    if node.get_descendants(vy_ast.ExtCall, include_self=True):
        return True

    for call in node.get_descendants(vy_ast.Call, include_self=True):
        func_t = call.func._metadata.get("type")
        if isinstance(func_t, RawCall):
            if func_t.get_mutability_at_call_site(call) > StateMutability.VIEW:
                return True
        elif isinstance(func_t, (Send, _CreateBase)):
            return True

    return False


class Stmt:
    """Lower Vyper statements to Venom IR."""

    def __init__(self, node: vy_ast.VyperNode, ctx: VenomCodegenContext):
        self.node = node
        self.ctx = ctx
        self.builder = ctx.builder

    def lower(self) -> None:
        """Dispatch to type-specific lowering method."""
        fn_name = f"lower_{type(self.node).__name__}"
        with tag_exceptions(self.node, fallback_exception_type=CodegenPanic, note=fn_name):
            method = getattr(self, fn_name, None)
            if method is None:  # pragma: nocover
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

        if is_unbounded_sequence_type(ltyp):
            rhs = Expr(node.value, self.ctx).lower()
            var = self.ctx.new_pointer_cell_variable(varname, ltyp)
            self._assign_unbounded_sequence_local(var, rhs, ltyp)
            return

        # Allocate memory for the new variable
        var = self.ctx.new_variable(varname, ltyp)

        rhs = Expr(node.value, self.ctx).lower()
        self._assign_value(var.value.ptr(), rhs, ltyp, src_node=node.value)

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

        if isinstance(target, vy_ast.Name) and target.id in self.ctx.variables:
            var = self.ctx.lookup(target.id)
            if var.is_pointer_cell:
                src = Expr(node.value, self.ctx).lower()
                self._assign_unbounded_sequence_local(var, src, target_typ)
                return

        # Special case: empty Bytestring/DynArray assignment — just zero the
        # length word.
        if has_length_word(target_typ) and self._is_empty_value(node.value):
            dst_ptr = self._get_target_ptr(target)
            self.ctx.ptr_store(dst_ptr, IRLiteral(0))
            return

        # IMPORTANT: Evaluate RHS first, then compute LHS target pointer.
        # This matches legacy codegen and ensures proper semantics for cases
        # like `c[0] = c.pop()` where RHS modifies array length.
        src = Expr(node.value, self.ctx).lower()
        dst_ptr = self._get_target_ptr(target)
        self._assign_value(dst_ptr, src, target_typ, src_node=node.value)

    def _assign_unbounded_sequence_local(self, var: LocalVariable, src: VyperValue, typ: VyperType):
        if not var.is_pointer_cell:  # pragma: nocover
            raise CompilerPanic("unbounded sequence local requires pointer-cell storage")
        if not is_unbounded_sequence_type(typ):  # pragma: nocover
            raise CompilerPanic(f"expected unbounded sequence type, got {typ}")
        value = self.ctx.copy_sequence_to_scratch(src, typ, annotation=var.name)
        self.ctx.ptr_store(var.value.ptr(), value.operand)

    def _assign_value(
        self, dst_ptr: Ptr, src: VyperValue, typ, *, src_node: vy_ast.VyperNode
    ) -> None:
        """Assign a VyperValue to a destination pointer.

        Handles both primitive word types (direct store) and complex types
        (with overlap-safe copying when source and dest are in the same
        address space).
        """
        if has_length_word(typ) and self._is_empty_value(src_node):
            # Empty bytes/string/dynarray assignment only needs a zero length word.
            self.ctx.ptr_store(dst_ptr, IRLiteral(0))
            return

        if typ._is_prim_word:
            self.ctx.ptr_store(dst_ptr, self.ctx.unwrap(src))
        else:
            self._copy_complex_type(dst_ptr, src, typ)

    def _copy_complex_type(self, dst_ptr: Ptr, src_vv: VyperValue, typ) -> None:
        """Copy complex type into `dst_ptr`.

        Materializes `src_vv` to memory (via unwrap), then stages through a
        temporary buffer when source and destination are both in memory
        (potential aliasing).  MemoryCopyElisionPass eliminates the staging
        copy when src/dst are provably non-overlapping.
        """
        src_loc = src_vv.location  # None for stack values, else DataLocation
        src_typ = src_vv.typ
        src = self.ctx.unwrap(src_vv)  # always a memory ptr for complex types

        # Stage when both src and dst are in memory to guard against aliasing.
        # MemoryCopyElisionPass will eliminate the redundant copy when
        # src/dst are provably non-overlapping (different allocas).
        if src_loc is DataLocation.MEMORY and dst_ptr.location is DataLocation.MEMORY:
            tmp_val = self.ctx.new_temporary_value(src_typ)
            assert isinstance(tmp_val.operand, IRVariable)
            self.ctx.copy_memory(tmp_val.operand, src, src_typ.memory_bytes_required)
            src = tmp_val.operand

        self._store_complex_type(dst_ptr, src, typ, src_typ)

    def _store_complex_type(self, dst_ptr: Ptr, src: IROperand, typ, src_typ) -> None:
        """Store complex value from memory `src` into `dst_ptr` (no overlap guard).

        Only called from `_copy_complex_type` which handles staging when needed.
        """
        if (
            src_typ != typ
            and dst_ptr.location is not DataLocation.MEMORY
            and not (isinstance(src_typ, _BytestringT) and isinstance(typ, _BytestringT))
        ):
            # Normalize source into destination layout before writing to
            # storage/transient/code locations that don't carry src_typ.
            normalized = self.ctx.new_temporary_value(typ)
            assert isinstance(normalized.operand, IRVariable)
            self.ctx.store_memory(src, normalized.operand, typ, src_typ=src_typ)
            src = normalized.operand
            src_typ = typ

        loc = dst_ptr.location
        is_slot_addressed = loc in (DataLocation.STORAGE, DataLocation.TRANSIENT)

        if is_slot_addressed:
            # DynArray special case: only copy length + actual elements, not full capacity.
            # This matches legacy codegen behavior (core.py:_dynarray_make_setter).
            if isinstance(typ, DArrayT):
                transient = loc is DataLocation.TRANSIENT
                self._copy_dynarray_to_storage(src, dst_ptr.operand, typ, transient=transient)
            else:
                # store_storage / store_transient handle single-word mload internally.
                store_fn = (
                    self.ctx.store_transient
                    if loc is DataLocation.TRANSIENT
                    else self.ctx.store_storage
                )
                store_fn(src, dst_ptr.operand, typ)
        elif loc == DataLocation.IMMUTABLES:
            # Immutables in constructor
            if typ.memory_bytes_required <= 32:
                assert isinstance(src, IRVariable)
                val = self.builder.mload(src)
                self.ctx.ptr_store(dst_ptr, val)
            else:
                self.ctx.store_immutable(src, dst_ptr.operand, typ)
        else:
            assert isinstance(dst_ptr.operand, IRVariable)
            # Memory destination: use layout-aware copy when types differ.
            self.ctx.store_memory(src, dst_ptr.operand, typ, src_typ=src_typ)

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
        src_vv = Expr(node.value, self.ctx).lower()
        src = self.ctx.unwrap(src_vv)

        # src is a pointer to the source tuple in memory
        src_tuple_typ = src_vv.typ
        dst_tuple_typ = target._metadata["type"]
        assert isinstance(src_tuple_typ, TupleT)
        assert isinstance(dst_tuple_typ, TupleT)
        targets = target.elements

        if self.ctx.is_dynamic_tuple_frame_type(src_tuple_typ):
            assert isinstance(src, IRVariable)
            self._lower_dynamic_tuple_frame_unpack(src, src_tuple_typ, dst_tuple_typ, targets)
            return

        # First pass: load all values from source tuple to temp variables.
        # This ensures correct semantics for overlapping cases like a,b = b,a.
        temp_vals = []
        src_offset = 0
        src_member_types = src_tuple_typ.member_types
        dst_member_types = dst_tuple_typ.member_types

        # If source and destination may alias in memory, snapshot the source tuple once.
        # This preserves tuple-assignment semantics (a, b = b, a) for complex members
        # without staging each element individually.
        src_expr = node.value.reduced()
        source_is_memory_view = isinstance(
            src_expr, (vy_ast.Name, vy_ast.Attribute, vy_ast.Subscript)
        )
        if (
            source_is_memory_view
            and src_vv.location is DataLocation.MEMORY
            and any(not t._is_prim_word for t in src_member_types)
        ):
            staged_src = self.ctx.new_temporary_value(src_tuple_typ)
            assert isinstance(staged_src.operand, IRVariable)
            self.ctx.copy_memory(staged_src.operand, src, src_tuple_typ.memory_bytes_required)
            src = staged_src.operand

        for src_elem_typ, dst_elem_typ in zip(src_member_types, dst_member_types):
            elem_ptr = self.builder.add(src, IRLiteral(src_offset))

            # Load the value
            val = self.ctx.load_memory(elem_ptr, src_elem_typ)
            temp_vals.append((val, src_elem_typ, dst_elem_typ))

            src_offset += src_elem_typ.memory_bytes_required

        # Second pass: assign each loaded value to its target
        for (val, src_elem_typ, dst_elem_typ), target_node in zip(temp_vals, targets):
            if isinstance(target_node, vy_ast.Name) and target_node.id in self.ctx.variables:
                var = self.ctx.lookup(target_node.id)
                if var.is_pointer_cell:
                    assert is_unbounded_sequence_type(dst_elem_typ)
                    assert isinstance(val, IRVariable)
                    src_vv = self.ctx.dynamic_memory_value(
                        val, src_elem_typ, annotation=target_node.id
                    )
                    self._assign_unbounded_sequence_local(var, src_vv, dst_elem_typ)
                    continue

            target_ptr = self._get_target_ptr(target_node)

            if dst_elem_typ._is_prim_word:
                self.ctx.ptr_store(target_ptr, val)
            else:
                # Complex element type: val is a memory pointer in source layout.
                self._store_complex_type(target_ptr, val, dst_elem_typ, src_elem_typ)

    def _lower_dynamic_tuple_frame_unpack(
        self,
        src: IRVariable,
        src_tuple_typ: TupleT,
        dst_tuple_typ: TupleT,
        targets: list[vy_ast.VyperNode],
    ) -> None:
        src_values = self.ctx.dynamic_tuple_frame_values(src, src_tuple_typ, annotation="unpack")
        dst_member_types = dst_tuple_typ.member_types

        for src_vv, dst_elem_typ, target_node in zip(src_values, dst_member_types, targets):
            src_elem_typ = src_vv.typ

            if isinstance(target_node, vy_ast.Name) and target_node.id in self.ctx.variables:
                var = self.ctx.lookup(target_node.id)
                if var.is_pointer_cell:
                    assert is_unbounded_sequence_type(dst_elem_typ)
                    self._assign_unbounded_sequence_local(var, src_vv, dst_elem_typ)
                    continue

            target_ptr = self._get_target_ptr(target_node)
            if dst_elem_typ._is_prim_word:
                self.ctx.ptr_store(target_ptr, self.ctx.unwrap(src_vv))
            else:
                self._store_complex_type(
                    target_ptr, self.ctx.unwrap(src_vv), dst_elem_typ, src_elem_typ
                )

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
        if not target_typ._is_prim_word:  # pragma: nocover
            raise TypeCheckFailure("AugAssign only valid for primitive types")

        # GHSA-4w26-8p97-f4jp: the target is computed and bounds-checked
        # before the RHS. Reject an RHS which could invalidate a complex
        # variable used to derive that target.
        rhs_writes = {access.variable for access in get_expr_writes(right_node)}
        for var in _referenced_variables(target):
            if var.typ._is_prim_word:
                continue
            if var in rhs_writes or (
                var.is_state_variable() and _contains_writeable_call(right_node)
            ):
                raise CodegenPanic("unreachable")

        # Get target pointer (with location info)
        dst_ptr = self._get_target_ptr(target)

        # Load current value
        left = self.ctx.ptr_load(dst_ptr)

        # Evaluate the RHS (AugAssign is always on primitives)
        right = Expr(right_node, self.ctx).lower_value()

        # Extract pow literal for bounds checking
        exp_literal = None
        if isinstance(op, vy_ast.Pow):
            right_reduced = right_node.reduced()
            if not isinstance(right_reduced, vy_ast.Int):  # pragma: nocover
                raise TypeCheckFailure("AugAssign pow requires literal exponent")
            exp_literal = right_reduced.value

        # Apply the operation (shared with lower_BinOp via apply_binop)
        result = apply_binop(self.builder, op, left, right, target_typ, exp_literal=exp_literal)

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
        assert isinstance(src, IRVariable)
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
                _get_empty_type(node)
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
                var = self.ctx.variables[varname]
                if var.is_pointer_cell:  # pragma: nocover
                    raise CompilerPanic("pointer-cell local has no direct assignment pointer")
                return var.value.ptr()

            # Check if it's an immutable assignment in constructor
            varinfo = target._expr_info.var_info
            if varinfo is not None and varinfo.is_immutable and self.ctx.is_ctor_context:
                return Ptr(IRLiteral(varinfo.position.position), DataLocation.IMMUTABLES)

            raise CompilerPanic(f"Unknown variable: {varname}")  # pragma: nocover

        elif isinstance(target, vy_ast.Attribute):
            # self.x = ... (state variable assignment)
            varinfo = target._expr_info.var_info

            if varinfo is not None:
                # Storage/transient variable - use actual location from varinfo
                if not varinfo.is_constant and not varinfo.is_immutable:
                    return Ptr(IRLiteral(varinfo.position.position), varinfo.location)

                # Immutable in constructor context
                if varinfo.is_immutable and self.ctx.is_ctor_context:
                    return Ptr(IRLiteral(varinfo.position.position), DataLocation.IMMUTABLES)

                if varinfo.is_constant:  # pragma: nocover
                    raise TypeCheckFailure("Cannot assign to constant")
                if varinfo.is_immutable:  # pragma: nocover
                    raise TypeCheckFailure("Cannot assign to immutable outside constructor")

            # Struct field access (point.x = ...)
            sub_typ = target.value._metadata.get("type")
            if isinstance(sub_typ, StructT) and target.attr in sub_typ.member_types:
                # Use Expr to compute the field pointer
                return Expr(target, self.ctx, as_ptr=True).lower().ptr()

            raise CompilerPanic(f"Unsupported attribute target: {target.attr}")  # pragma: nocover

        elif isinstance(target, vy_ast.Subscript):
            # x[i] = ... or self.arr[i] = ... or self.map[key] = ...
            # Use Expr to compute the element pointer/slot
            return Expr(target, self.ctx, as_ptr=True).lower().ptr()

        raise CompilerPanic(f"Unsupported assignment target: {type(target)}")  # pragma: nocover

    def _can_encode_from_source_return_layout(self, dst_typ: VyperType, src_typ: VyperType) -> bool:
        """
        True when `src_typ` has a concrete memory layout and can be ABI-encoded
        directly for a declared return type `dst_typ`.

        This covers bounded bytes/string values returned through INF supertypes,
        including tuple members such as raw_call's `(bool, Bytes[N])` checkable
        result returned as `(bool, Bytes[INF])`.
        """
        return dst_typ.compare_type(src_typ)

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
                else:  # pragma: nocover
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
        location = array_vv.location
        assert location is not None

        # Determine word scale based on location
        # Storage/Transient: 1 slot per word, Memory: 32 bytes per word
        is_slot_addressed = location in (DataLocation.STORAGE, DataLocation.TRANSIENT)
        word_scale = 1 if is_slot_addressed else 32

        # Get length and bound
        length: IROperand
        if isinstance(array_typ, DArrayT):
            # Dynamic array: length is first word
            length = self.ctx.load_word(array, location)
            bound = array_typ.count
        elif isinstance(array_typ, SArrayT):
            # Static array: length is compile-time constant
            length = IRLiteral(array_typ.count)
            bound = array_typ.count
        else:  # pragma: nocover
            raise CompilerPanic(f"Cannot iterate over type: {array_typ}")

        # Element size (in slots for storage, bytes for memory)
        elem_size = array_typ.value_type.get_size_in(location)

        # Allocate loop variable (copy of element, not reference)
        item_local = self.ctx.new_variable(varname, target_type, mutable=False)
        assert isinstance(item_local.value.operand, IRVariable)
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
        if isinstance(array_typ, DArrayT) and is_bounded_length(bound):
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

            # Copy element to loop variable (always in memory).
            # Note: type mismatches (target_type != value_type) are possible
            # for any source location (the type checker allows e.g.
            # Bytes[704] target with Bytes[540] elements). For non-memory
            # sources, the linear copy is safe for flat types since the
            # source is smaller than the destination buffer. Only the
            # memory path uses type-aware copying (store_memory).
            dst = item_local.value.operand
            if is_slot_addressed:
                # Word-addressed (STORAGE, TRANSIENT)
                self.ctx.slot_to_memory(elem_addr, dst, elem_size, location)
            elif location is not DataLocation.MEMORY:
                # Byte-addressed non-memory (IMMUTABLES, CODE, CALLDATA):
                # location-aware copy via load_word dispatch
                self.ctx.copy_to_memory(dst, elem_addr, elem_size, location)
            elif target_type._is_prim_word:
                # Memory, single word
                val = self.builder.mload(elem_addr)
                self.builder.mstore(dst, val)
            else:
                # Memory, complex type: type-aware copy handles
                # layout mismatches (e.g. DynArray[Bytes[540]] -> Bytes[704])
                self.ctx.store_memory(elem_addr, dst, target_type, src_typ=array_typ.value_type)

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
        if self.ctx.break_target is None:  # pragma: nocover
            raise CompilerPanic("break outside loop")
        self.builder.jmp(self.ctx.break_target)

    def lower_Continue(self) -> None:
        """Lower continue statement - jump to loop increment."""
        if self.ctx.continue_target is None:  # pragma: nocover
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

        if func_t is None:  # pragma: nocover
            raise CompilerPanic("Return outside function")

        # Evaluate return value if present
        ret_val: Optional[IROperand] = None
        ret_src_typ = None
        if node.value is not None:
            if (
                self.ctx.return_pc is None
                and self._try_lower_external_dynamic_tuple_literal_return(node.value, func_t)
            ):
                return

            # lower() preserves source type so return coercions can use
            # layout-aware copying when source and declared return type differ.
            ret_vv = Expr(node.value, self.ctx).lower()
            ret_val = self.ctx.unwrap(ret_vv)
            ret_src_typ = ret_vv.typ

        # Dispatch: internal vs external
        if self.ctx.return_pc is not None:
            self._lower_internal_return(ret_val, func_t, ret_src_typ)
        else:
            self._lower_external_return(ret_val, func_t, ret_src_typ)

    def _try_lower_external_dynamic_tuple_literal_return(
        self, value_node: vy_ast.VyperNode, func_t: ContractFunctionT
    ) -> bool:
        ret_typ = func_t.return_type
        if (
            func_t.do_raw_return
            or ret_typ is None
            or not isinstance(ret_typ, TupleT)
            or not isinstance(value_node, vy_ast.Tuple)
            or not type_contains_unbounded_sequence(ret_typ)
        ):
            return False

        arg_vvs = []
        for i, elem in enumerate(value_node.elements):
            member_t = ret_typ.member_types[i]
            arg_vv = Expr(elem, self.ctx).lower()
            copy_composites = later_expressions_can_mutate_memory_or_storage(
                value_node.elements[i + 1 :]
            )
            arg_vvs.append(
                self._freeze_external_tuple_return_member(
                    arg_vv, member_t, annotation="return", copy_composites=copy_composites
                )
            )

        src_typ = TupleT(tuple(arg_vv.typ for arg_vv in arg_vvs))
        if not self._can_encode_from_source_return_layout(ret_typ, src_typ):
            raise CompilerPanic(
                f"semantic analysis should reject returning {src_typ} as {ret_typ}"
            )  # pragma: nocover

        self.ctx.emit_nonreentrant_unlock(func_t)
        external_return_type = calculate_type_for_external_return(ret_typ)

        self._emit_external_dynamic_tuple_return(
            arg_vvs, src_typ, wrap_outer=external_return_type is not ret_typ
        )
        return True

    def _freeze_external_tuple_return_member(
        self, arg_vv: VyperValue, target_typ: VyperType, annotation: str, copy_composites: bool
    ) -> VyperValue:
        """Snapshot tuple literal return members before later elements run.

        ABI encoding happens after the full tuple is evaluated. Without this,
        a later element with side effects, e.g. `return x, x.pop()`, can mutate
        the memory/storage pointed to by an earlier member before it is encoded.
        """
        target_has_nested_inf = type_contains_unbounded_sequence(
            target_typ
        ) and not is_unbounded_sequence_type(target_typ)
        source_has_nested_inf = type_contains_unbounded_sequence(
            arg_vv.typ
        ) and not is_unbounded_sequence_type(arg_vv.typ)
        if target_has_nested_inf or source_has_nested_inf:
            raise CompilerPanic(
                "semantic analysis should reject nested INF tuple returns"
            )  # pragma: nocover

        return self.ctx.snapshot_value_for_delayed_use(
            arg_vv, target_typ, annotation=annotation, copy_composites=copy_composites
        )

    def _emit_external_dynamic_tuple_return(
        self, arg_vvs: list[VyperValue], encode_typ: TupleT, wrap_outer: bool
    ) -> None:
        if wrap_outer:
            # External returns are always ABI tuples. A declared singleton
            # tuple `-> (T,)` is therefore returned as `((T,),)`.
            encoded_size = self.ctx.checked_add(
                IRLiteral(32), runtime_abi_size_for_encode(self.ctx, arg_vvs, encode_typ)
            )
            buf_ptr = self.ctx.allocate_scratch(encoded_size)
            self.builder.mstore(buf_ptr, IRLiteral(32))
            child_dst = self.builder.add(buf_ptr, IRLiteral(32))
            child_len = abi_encode_values_to_buf(self.ctx, child_dst, arg_vvs, encode_typ)
            encoded_len = self.ctx.checked_add(IRLiteral(32), child_len)
            self.builder.return_(buf_ptr, encoded_len)
            return

        encoded_size = runtime_abi_size_for_encode(self.ctx, arg_vvs, encode_typ)
        buf_ptr = self.ctx.allocate_scratch(encoded_size)
        encoded_len = abi_encode_values_to_buf(self.ctx, buf_ptr, arg_vvs, encode_typ)
        self.builder.return_(buf_ptr, encoded_len)

    def _lower_internal_return(
        self, ret_val: Optional[IROperand], func_t: ContractFunctionT, ret_src_typ=None
    ) -> None:
        """Lower internal function return.

        For internal functions:
        - Nonreentrant unlock (if applicable)
        - Load return values and pass on stack
        - ret to return_pc
        """
        return_pc = self.ctx.return_pc
        assert return_pc is not None  # Caller ensures this

        # Nonreentrant unlock. The return expression has already been
        # evaluated by the caller, so this runs at function exit.
        self.ctx.emit_nonreentrant_unlock(func_t)

        if ret_val is None:
            self.builder.ret(return_pc)
            return

        returns_count = returns_stack_count(func_t)
        dynamic_returns_count = returns_dynamic_count(func_t)
        ret_typ = func_t.return_type
        assert ret_typ is not None

        if dynamic_returns_count > 0:
            assert isinstance(ret_val, IRVariable)
            if self.ctx.is_dynamic_tuple_frame_type(ret_typ):
                assert isinstance(ret_typ, TupleT)
                assert isinstance(ret_src_typ, TupleT)
                self._emit_dynamic_tuple_internal_return(ret_val, ret_typ, ret_src_typ, return_pc)
                return

            assert returns_count == 0
            size = self.ctx.sequence_runtime_size(ret_val, ret_typ)
            self.builder.dret(IRLiteral(dynamic_returns_count), ret_val, size, return_pc)
            return

        elif returns_count > 0:
            # Stack return - load values and pass to ret
            ret_vals: list[IROperand] = []

            if hasattr(ret_typ, "tuple_items"):
                # Tuple/struct return - load each element from memory pointer
                # This handles both multi-element tuples AND single-element structs
                for i, (_k, _elem_t) in enumerate(ret_typ.tuple_items()):
                    src_ptr = self.builder.add(ret_val, IRLiteral(i * 32))
                    ret_vals.append(self.builder.mload(src_ptr))
            else:
                # Primitive single value - just use directly
                ret_vals.append(ret_val)

            self.builder.ret(*ret_vals, return_pc)

        elif self.ctx.return_buffer is not None:
            # Memory return - store to buffer, caller reads it
            self.ctx.store_memory(ret_val, self.ctx.return_buffer, ret_typ, src_typ=ret_src_typ)
            self.builder.ret(return_pc)

        else:  # pragma: nocover
            raise CompilerPanic("Internal function missing return mechanism")

    def _dynamic_return_member_size(
        self, member_ptr: IRVariable, dst_typ: VyperType, src_typ: VyperType
    ) -> IROperand:
        if isinstance(dst_typ, _BytestringT) and isinstance(src_typ, _BytestringT):
            return self.ctx.bytestring_runtime_size(member_ptr)

        if isinstance(dst_typ, DArrayT) and isinstance(src_typ, DArrayT):
            if is_unbounded_dynarray_type(dst_typ) or is_unbounded_dynarray_type(src_typ):
                return self.ctx.dynarray_runtime_size(member_ptr, dst_typ)
            return IRLiteral(src_typ.memory_bytes_required)

        if type_contains_unbounded_sequence(dst_typ) or type_contains_unbounded_sequence(src_typ):
            raise CompilerPanic(
                "semantic analysis should reject nested INF tuple internal returns"
            )  # pragma: nocover

        return IRLiteral(src_typ.memory_bytes_required)

    def _emit_dynamic_tuple_internal_return(
        self, ret_val: IRVariable, ret_typ: TupleT, ret_src_typ: TupleT, return_pc: IRVariable
    ) -> None:
        dst_member_types = ret_typ.member_types
        src_member_types = ret_src_typ.member_types

        src_is_frame = self.ctx.is_dynamic_tuple_frame_type(ret_src_typ)
        src_offset = 0
        ordinary_returns: list[IROperand] = []
        dynamic_return_operands: list[IROperand] = []

        for i, (dst_member_t, src_member_t) in enumerate(zip(dst_member_types, src_member_types)):
            member_value: IROperand | None
            member_ptr: IRVariable | None
            if src_is_frame:
                cell = self.builder.add(ret_val, IRLiteral(i * 32))
                if src_member_t._is_prim_word:
                    member_value = self.builder.mload(cell)
                    member_ptr = None
                else:
                    member_value = None
                    member_ptr = self.builder.mload(cell)
                    assert isinstance(member_ptr, IRVariable)
            else:
                if type_contains_unbounded_sequence(src_member_t):
                    raise CompilerPanic(
                        "dynamic tuple returns with INF members should use a frame"
                    )  # pragma: nocover
                member_ptr = self.builder.add(ret_val, IRLiteral(src_offset))
                assert isinstance(member_ptr, IRVariable)
                if src_member_t._is_prim_word:
                    member_value = self.ctx.load_memory(member_ptr, src_member_t)
                else:
                    member_value = None
                src_offset += src_member_t.memory_bytes_required

            if dst_member_t._is_prim_word:
                assert member_value is not None
                ordinary_returns.append(member_value)
                continue

            assert member_ptr is not None
            if (
                dst_member_t != src_member_t
                and not type_contains_unbounded_sequence(dst_member_t)
                and not type_contains_unbounded_sequence(src_member_t)
            ):
                normalized = self.ctx.new_temporary_value(dst_member_t)
                assert isinstance(normalized.operand, IRVariable)
                self.ctx.store_memory(
                    member_ptr, normalized.operand, dst_member_t, src_typ=src_member_t
                )
                member_ptr = normalized.operand
                src_member_t = dst_member_t

            if not dst_member_t._is_prim_word:
                size = self._dynamic_return_member_size(member_ptr, dst_member_t, src_member_t)
                dynamic_return_operands.extend([member_ptr, size])
                continue

            ordinary_returns.append(member_ptr)

        dyn_count = len(dynamic_return_operands) // 2
        self.builder.dret(
            IRLiteral(dyn_count), *ordinary_returns, *dynamic_return_operands, return_pc
        )

    def _emit_external_unbounded_sequence_return(
        self, ret_val: IRVariable, ret_typ: VyperType, external_return_type: VyperType
    ) -> None:
        assert is_unbounded_sequence_type(ret_typ)

        ret_vv = self.ctx.dynamic_memory_value(ret_val, ret_typ, annotation="return")
        tail_len = runtime_abi_size_for_encode(self.ctx, [ret_vv], ret_typ)
        encoded_size = self.ctx.checked_add(IRLiteral(32), tail_len)
        buf_ptr = self.ctx.allocate_scratch(encoded_size)
        encoded_len = abi_encode_to_buf(self.ctx, buf_ptr, ret_val, external_return_type)
        self.builder.return_(buf_ptr, encoded_len)

    def _lower_external_return(
        self, ret_val: Optional[IROperand], func_t: ContractFunctionT, ret_src_typ=None
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

        can_encode_from_src = (
            ret_src_typ is not None
            and not type_contains_unbounded_sequence(ret_src_typ)
            and self._can_encode_from_source_return_layout(ret_typ, ret_src_typ)
        )

        if (
            ret_src_typ is not None
            and not ret_typ._is_prim_word
            and not (isinstance(ret_typ, _BytestringT) and isinstance(ret_src_typ, _BytestringT))
            and ret_src_typ != ret_typ
            and not can_encode_from_src
            and ret_val is not None
        ):
            normalized = self.ctx.new_temporary_value(ret_typ)
            assert isinstance(normalized.operand, IRVariable)
            self.ctx.store_memory(ret_val, normalized.operand, ret_typ, src_typ=ret_src_typ)
            ret_val = normalized.operand
            ret_src_typ = ret_typ

        # Raw return: return bytes directly without ABI encoding
        # The @raw_return decorator bypasses ABI encoding for proxy patterns
        if func_t.do_raw_return:
            if is_unbounded_bytestring_type(ret_typ):
                assert isinstance(ret_val, IRVariable)
                return_len = self.builder.mload(ret_val)
                return_offset = self.builder.add(ret_val, IRLiteral(32))
                self.builder.return_(return_offset, return_len)
                return

            # ret_val is a pointer to [length (32 bytes)][data...]
            # Copy to a fresh buffer to ensure it's in memory
            buf_val = self.ctx.new_temporary_value(ret_typ)
            assert isinstance(buf_val.operand, IRVariable)
            self.ctx.store_memory(ret_val, buf_val.operand, ret_typ, src_typ=ret_src_typ)

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
        encode_typ = external_return_type
        if can_encode_from_src:
            assert ret_src_typ is not None
            encode_typ = calculate_type_for_external_return(ret_src_typ)

        if is_unbounded_sequence_type(ret_typ):
            assert isinstance(ret_val, IRVariable)
            self._emit_external_unbounded_sequence_return(ret_val, ret_typ, external_return_type)
            return

        if (
            self.ctx.is_dynamic_tuple_frame_type(ret_typ)
            and ret_src_typ is not None
            and type_contains_unbounded_sequence(ret_src_typ)
        ):
            assert isinstance(ret_typ, TupleT)
            assert isinstance(ret_val, IRVariable)
            arg_vvs = self.ctx.dynamic_tuple_frame_values(ret_val, ret_typ, annotation="return")

            self._emit_external_dynamic_tuple_return(
                arg_vvs, ret_typ, wrap_outer=external_return_type is not ret_typ
            )
            return

        maxlen = encode_typ.abi_type.size_bound()

        # Allocate return buffer
        buf = self.ctx.allocate_buffer(maxlen)

        # ABI encode using the declared return ABI shape, or a compatible
        # bounded source layout when returning through an INF supertype.
        encoded_len = abi_encode_to_buf(self.ctx, buf._ptr, ret_val, encode_typ)

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

        # Lower all argument expressions and snapshot before later arguments
        # can mutate memory/storage that earlier arguments point at.
        arg_vals = []
        for i, arg in enumerate(arg_nodes):
            arg_vv = Expr(arg, self.ctx).lower()
            copy_composites = later_expressions_can_mutate_memory_or_storage(arg_nodes[i + 1 :])
            arg_vals.append(
                self.ctx.snapshot_value_for_delayed_use(
                    arg_vv, annotation="log", copy_composites=copy_composites
                )
            )

        # Split into indexed (topics) and non-indexed (data)
        topic_vals = []
        data_vals = []

        for arg_vv, is_indexed in zip(arg_vals, event.indexed):
            if is_indexed:
                topic_vals.append(arg_vv)
            else:
                data_vals.append(arg_vv)

        # Build topics list - starts with event signature hash
        topics: list[IROperand] = [IRLiteral(event.event_id)]

        for arg_vv in topic_vals:
            topic = self._encode_log_topic(self.ctx.unwrap(arg_vv), arg_vv.typ)
            topics.append(topic)

        # Encode non-indexed data to buffer
        abi_buf_ptr: IROperand
        encoded_len: IROperand
        if data_vals:
            # Event declarations reject INF members, so log data is statically bounded here.
            data_typs = tuple(arg_vv.typ for arg_vv in data_vals)
            tuple_typ = TupleT(data_typs)
            bufsz = tuple_typ.abi_type.size_bound()

            # Allocate ABI encoding output buffer
            abi_buf = self.ctx.allocate_buffer(bufsz)
            abi_buf_ptr = abi_buf._ptr

            # ABI encode the tuple
            encoded_len = abi_encode_values_to_buf(self.ctx, abi_buf_ptr, data_vals, tuple_typ)
        else:
            # No data - use zero size
            log_buf = self.ctx.allocate_buffer(0, annotation="log empty buffer")
            abi_buf_ptr = log_buf._ptr
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
            assert isinstance(val, IRVariable)
            length = self.builder.mload(val)
            return self.builder.sha3(data_ptr, length)

        else:  # pragma: nocover
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
                revert_buffer = self.ctx.allocate_buffer(0, annotation="user assert revert buffer")
                self.builder.revert(revert_buffer._ptr, IRLiteral(0))

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
                revert_buffer = self.ctx.allocate_buffer(0, annotation="user raise revert buffer")
                self.builder.revert(revert_buffer._ptr, IRLiteral(0))
        elif isinstance(node.exc, vy_ast.Name) and node.exc.id == "UNREACHABLE":
            # UNREACHABLE: invalid opcode
            with self.builder.error_context("raise unreachable"):
                self.builder.invalid()
        else:
            msg_type = node.exc._metadata.get("type")
            if isinstance(msg_type, ErrorT):
                self._revert_with_custom_error(node.exc, msg_type)
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
            return

        ok_block = self.builder.create_block("assert_ok")
        fail_block = self.builder.create_block("assert_fail")

        self.builder.jnz(cond, ok_block.label, fail_block.label)

        # Fail block: revert with reason
        self.builder.append_block(fail_block)
        self.builder.set_block(fail_block)
        msg_type = msg._metadata.get("type")
        if isinstance(msg_type, ErrorT):
            self._revert_with_custom_error(msg, msg_type)
        else:
            self._revert_with_reason(msg)

        # Ok block: continue
        self.builder.append_block(ok_block)
        self.builder.set_block(ok_block)

    def _custom_error_arg_nodes(self, call: vy_ast.Call, error_t: ErrorT) -> list[vy_ast.VyperNode]:
        if len(call.keywords) > 0:
            kwarg_lookup = {kw.arg: kw.value for kw in call.keywords}
            return [kwarg_lookup[name] for name in error_t.arguments.keys()]

        return call.args

    def _revert_with_custom_error(self, msg: vy_ast.VyperNode, error_t: ErrorT) -> None:
        """Emit revert with custom error selector and ABI-encoded arguments."""
        assert isinstance(msg, vy_ast.Call)

        arg_nodes = self._custom_error_arg_nodes(msg, error_t)
        old_constancy = self.ctx.constancy
        try:
            self.ctx.constancy = Constancy.Constant
            arg_vvs = []
            for i, arg_node in enumerate(arg_nodes):
                arg_vv = Expr(arg_node, self.ctx).lower()
                copy_composites = later_expressions_can_mutate_memory_or_storage(arg_nodes[i + 1 :])
                arg_vvs.append(
                    self.ctx.snapshot_value_for_delayed_use(
                        arg_vv, annotation="custom error", copy_composites=copy_composites
                    )
                )
        finally:
            self.ctx.constancy = old_constancy

        arg_types = tuple(arg_vv.typ for arg_vv in arg_vvs)
        args_tuple_t = TupleT(arg_types)

        bufsz = args_tuple_t.abi_type.size_bound() + 32
        buf = self.ctx.allocate_buffer(bufsz, annotation="custom error revert buffer")
        self.builder.mstore(buf._ptr, IRLiteral(error_t.selector))

        if len(arg_nodes) == 0:
            revert_offset = self.builder.add(buf._ptr, IRLiteral(28))
            with self.builder.error_context("user revert with custom error"):
                self.builder.revert(revert_offset, IRLiteral(4))
            return

        payload_buf = self.builder.add(buf._ptr, IRLiteral(32))
        encoded_len = abi_encode_values_to_buf(self.ctx, payload_buf, arg_vvs, args_tuple_t)

        revert_offset = self.builder.add(buf._ptr, IRLiteral(28))
        revert_len = self.builder.add(IRLiteral(4), encoded_len)
        with self.builder.error_context("user revert with custom error"):
            self.builder.revert(revert_offset, revert_len)

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

        # msg is materialized to memory here
        # We need to store it at a location so we can encode the tuple
        # For a tuple (string,), we store the string pointer, then encode
        tuple_buf = self.ctx.allocate_buffer(wrapped_typ.memory_bytes_required)
        self.ctx.store_vyper_value(msg_vv, tuple_buf._ptr, msg_typ)

        # ABI encode the wrapped message to payload buffer
        encoded_len = abi_encode_to_buf(self.ctx, payload_buf, tuple_buf._ptr, wrapped_typ)

        # Revert from buf+28 (so selector is at bytes 0-3) with length 4 + encoded_len
        revert_offset = self.builder.add(buf._ptr, IRLiteral(28))
        revert_len = self.builder.add(IRLiteral(4), encoded_len)
        with self.builder.error_context("user revert with reason"):
            self.builder.revert(revert_offset, revert_len)
