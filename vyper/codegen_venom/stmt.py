"""
Lower Vyper AST statements to Venom IR.

This module handles statement codegen: assignments, augmented assignments,
and other statement types. Complex multi-word assignments (structs, arrays)
are deferred to later tasks.
"""
from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, TypeCheckFailure
from vyper.semantics.types import DecimalT, IntegerT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import DArrayT, HashMapT, SArrayT
from vyper.semantics.types.user import StructT
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

from .context import VenomCodegenContext
from .expr import Expr


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

        1. Allocate memory for the variable via new_variable()
        2. Evaluate the RHS expression
        3. Store the value at the allocated pointer
        """
        ltyp = self.node.target._metadata["type"]
        varname = self.node.target.id

        # Allocate memory for the new variable
        ptr = self.ctx.new_variable(varname, ltyp)

        # AnnAssign always has a value in Vyper (semantic analysis ensures this)
        assert self.node.value is not None

        # Lower the RHS and store at the allocated pointer
        rhs = Expr(self.node.value, self.ctx).lower()
        self._store_value(ptr, rhs, ltyp)

    def lower_Assign(self) -> None:
        """Lower regular assignment.

        Example: `x = 5` or `x[i] = 5` or `self.x = 5`

        For primitive types (single word), this is a simple store.
        For complex types (multi-word), overlap detection is needed
        to avoid trampling src during copy - but that's deferred to
        later tasks.
        """
        # Evaluate source value
        src = Expr(self.node.value, self.ctx).lower()

        # Get target pointer
        target = self.node.target
        target_typ = target._metadata["type"]

        # Handle tuple unpacking separately
        if isinstance(target, vy_ast.Tuple):
            raise CompilerPanic("Tuple unpacking not yet implemented")

        # Get the destination pointer and determine storage vs memory
        dst_ptr = self._get_target_ptr(target)
        is_storage = self._is_storage_target(target)

        # For primitive word types, no overlap concern - just store
        if target_typ._is_prim_word:
            self._store_value(dst_ptr, src, target_typ, is_storage)
        else:
            # Multi-word types need overlap detection - defer to later tasks
            raise CompilerPanic("Complex type assignment not yet implemented")

    def lower_AugAssign(self) -> None:
        """Lower augmented assignment.

        Example: `x += 5` or `self.x *= 2` or `self.arr[i] += 1`

        1. Load current value from target
        2. Apply binary operation
        3. Store result back to target

        Only supports primitive word types (no structs/arrays).
        """
        target = self.node.target
        target_typ = target._metadata["type"]
        op = self.node.op
        right_node = self.node.value

        # AugAssign only works on primitive word types
        if not target_typ._is_prim_word:
            raise TypeCheckFailure("AugAssign only valid for primitive types")

        # Get target pointer and determine storage vs memory
        dst_ptr = self._get_target_ptr(target)
        is_storage = self._is_storage_target(target)

        # Load current value
        left = self._load_value(dst_ptr, target_typ, is_storage)

        # Evaluate the RHS
        right = Expr(right_node, self.ctx).lower()

        # Apply the operation
        result = self._apply_augassign_op(op, left, right, target_typ, right_node)

        # Store result back
        self._store_value(dst_ptr, result, target_typ, is_storage)

    # === Helper Methods ===

    def _get_target_ptr(self, target: vy_ast.VyperNode) -> IROperand:
        """Get pointer to assignment target.

        Handles:
        - Name: local variable or state variable
        - Subscript: array/mapping access
        - Attribute: struct field or state variable (self.x)

        Returns pointer/slot. Caller uses _is_storage_target to determine
        whether to use sload/sstore or mload/mstore.
        """
        if isinstance(target, vy_ast.Name):
            varname = target.id

            # Check if it's a local variable
            if varname in self.ctx.variables:
                return self.ctx.lookup_ptr(varname)

            raise CompilerPanic(f"Unknown variable: {varname}")

        elif isinstance(target, vy_ast.Attribute):
            # self.x = ... (state variable assignment)
            varinfo = target._expr_info.var_info

            if varinfo is not None:
                # Storage variable - simple slot
                if not varinfo.is_constant and not varinfo.is_immutable:
                    return IRLiteral(varinfo.position.position)

                # Immutable in constructor context
                if varinfo.is_immutable and self.ctx.is_ctor_context:
                    return IRLiteral(varinfo.position.position)

                if varinfo.is_constant:
                    raise TypeCheckFailure("Cannot assign to constant")
                if varinfo.is_immutable:
                    raise TypeCheckFailure("Cannot assign to immutable outside constructor")

            # Struct field access (point.x = ...)
            sub_typ = target.value._metadata.get("type")
            if isinstance(sub_typ, StructT) and target.attr in sub_typ.member_types:
                # Use Expr to compute the field pointer
                return Expr(target, self.ctx).lower()

            raise CompilerPanic(f"Unsupported attribute target: {target.attr}")

        elif isinstance(target, vy_ast.Subscript):
            # x[i] = ... or self.arr[i] = ... or self.map[key] = ...
            # Use Expr to compute the element pointer/slot
            return Expr(target, self.ctx).lower()

        raise CompilerPanic(f"Unsupported assignment target: {type(target)}")

    def _is_storage_target(self, target: vy_ast.VyperNode) -> bool:
        """Check if assignment target is storage.

        Returns True if the target is in storage/transient, False for memory.
        """
        # self.x -> storage
        if isinstance(target, vy_ast.Attribute):
            if isinstance(target.value, vy_ast.Name) and target.value.id == "self":
                varinfo = target._expr_info.var_info
                if varinfo is not None and not varinfo.is_constant and not varinfo.is_immutable:
                    return True
            # Nested: self.x.field
            return self._is_storage_target(target.value)

        # Subscript on storage: self.arr[i], self.map[key]
        if isinstance(target, vy_ast.Subscript):
            return self._is_storage_target(target.value)

        # Local variables are in memory
        if isinstance(target, vy_ast.Name):
            return False

        return False

    def _load_value(self, ptr: IROperand, typ, is_storage: bool = False) -> IROperand:
        """Load a value from a pointer.

        Args:
            ptr: Pointer to load from (memory ptr or storage slot)
            typ: Type of value being loaded
            is_storage: True if ptr is storage/transient, False for memory
        """
        if is_storage:
            # Storage/transient variable - use sload
            # TODO: Support transient storage
            return self.builder.sload(ptr)
        else:
            # Memory variable - use mload
            return self.builder.mload(ptr)

    def _store_value(self, ptr: IROperand, val: IROperand, typ, is_storage: bool = False) -> None:
        """Store a value to a pointer.

        Args:
            ptr: Pointer to store to (memory ptr or storage slot)
            val: Value to store
            typ: Type of value being stored
            is_storage: True if ptr is storage/transient, False for memory
        """
        if is_storage:
            # Storage variable - use sstore
            # TODO: Support transient storage
            self.builder.sstore(val, ptr)
        else:
            # Memory variable - use mstore
            self.builder.mstore(val, ptr)

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
    # These mirror Expr._safe_* methods

    def _safe_add(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Add with overflow checking."""
        res = self.builder.add(x, y)

        if isinstance(typ, (IntegerT, DecimalT)) and typ.bits < 256:
            return self._clamp_basetype(res, typ)

        if isinstance(typ, (IntegerT, DecimalT)):
            if typ.is_signed:
                y_neg = self.builder.slt(y, IRLiteral(0))
                res_lt_x = self.builder.slt(res, x)
                ok = self.builder.eq(y_neg, res_lt_x)
            else:
                ok = self.builder.iszero(self.builder.lt(res, x))
            self.builder.assert_(ok)

        return res

    def _safe_sub(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Subtract with overflow checking."""
        res = self.builder.sub(x, y)

        if isinstance(typ, (IntegerT, DecimalT)) and typ.bits < 256:
            return self._clamp_basetype(res, typ)

        if isinstance(typ, (IntegerT, DecimalT)):
            if typ.is_signed:
                y_neg = self.builder.slt(y, IRLiteral(0))
                res_gt_x = self.builder.sgt(res, x)
                ok = self.builder.eq(y_neg, res_gt_x)
            else:
                ok = self.builder.iszero(self.builder.gt(res, x))
            self.builder.assert_(ok)

        return res

    def _safe_mul(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Multiply with overflow checking."""
        res = self.builder.mul(x, y)

        if isinstance(typ, (IntegerT, DecimalT)):
            is_signed = typ.is_signed

            if typ.bits > 128:
                DIV = self.builder.sdiv if is_signed else self.builder.div
                div_check = self.builder.eq(DIV(res, y), x)
                y_zero = self.builder.iszero(y)
                ok = self.builder.or_(div_check, y_zero)

                if is_signed and typ.bits == 256:
                    min_int = 1 << 255
                    x_is_min = self.builder.eq(x, IRLiteral(min_int))
                    y_is_neg1 = self.builder.iszero(self.builder.not_(y))
                    special_case = self.builder.and_(x_is_min, y_is_neg1)
                    not_special = self.builder.iszero(special_case)
                    ok = self.builder.and_(ok, not_special)

                self.builder.assert_(ok)

            if isinstance(typ, DecimalT):
                DIV = self.builder.sdiv if is_signed else self.builder.div
                res = DIV(res, IRLiteral(typ.divisor))

            if typ.bits < 256 or isinstance(typ, DecimalT):
                res = self._clamp_basetype(res, typ)

        return res

    def _safe_div(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Decimal division with overflow checking."""
        if not isinstance(typ, DecimalT):
            raise CompilerPanic("/ operator only valid for decimals")

        x_scaled = self.builder.mul(x, IRLiteral(typ.divisor))

        if typ.is_signed:
            y_gt_zero = self.builder.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = self.builder.gt(y, IRLiteral(0))
        self.builder.assert_(y_gt_zero)

        DIV = self.builder.sdiv if typ.is_signed else self.builder.div
        res = DIV(x_scaled, y)

        return self._clamp_basetype(res, typ)

    def _safe_floordiv(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Integer floor division with overflow checking."""
        if not isinstance(typ, IntegerT):
            raise CompilerPanic("// operator only valid for integers")

        is_signed = typ.is_signed

        if is_signed:
            y_gt_zero = self.builder.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = self.builder.gt(y, IRLiteral(0))
        self.builder.assert_(y_gt_zero)

        DIV = self.builder.sdiv if is_signed else self.builder.div
        res = DIV(x, y)

        if is_signed and typ.bits == 256:
            min_int = 1 << 255
            x_is_min = self.builder.eq(x, IRLiteral(min_int))
            y_is_neg1 = self.builder.iszero(self.builder.not_(y))
            special_case = self.builder.and_(x_is_min, y_is_neg1)
            ok = self.builder.iszero(special_case)
            self.builder.assert_(ok)
        elif is_signed and typ.bits < 256:
            res = self._clamp_basetype(res, typ)

        return res

    def _safe_mod(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Modulo with divisor check."""
        if not isinstance(typ, IntegerT):
            raise CompilerPanic("% operator only valid for integers")

        is_signed = typ.is_signed

        if is_signed:
            y_gt_zero = self.builder.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = self.builder.gt(y, IRLiteral(0))
        self.builder.assert_(y_gt_zero)

        MOD = self.builder.smod if is_signed else self.builder.mod
        return MOD(x, y)

    def _safe_pow(
        self, x: IROperand, y: IROperand, typ, right_node: vy_ast.VyperNode
    ) -> IROperand:
        """Exponentiation - only with literal exponent for bounds checking."""
        if not isinstance(typ, IntegerT):
            raise TypeCheckFailure("pow only valid for integers")

        # For AugAssign, we require a literal exponent for bounds check
        right_reduced = right_node.reduced()
        if not isinstance(right_reduced, vy_ast.Int):
            raise TypeCheckFailure("AugAssign pow requires literal exponent")

        from vyper.codegen.arithmetic import calculate_largest_base

        is_signed = typ.is_signed
        bits = typ.bits
        exp_val = right_reduced.value

        if exp_val in (0, 1):
            ok = IRLiteral(1)
        else:
            lower_bound, upper_bound = calculate_largest_base(exp_val, bits, is_signed)
            if is_signed:
                ge_lower = self.builder.iszero(self.builder.slt(x, IRLiteral(lower_bound)))
                le_upper = self.builder.iszero(self.builder.sgt(x, IRLiteral(upper_bound)))
                ok = self.builder.and_(ge_lower, le_upper)
            else:
                ok = self.builder.iszero(self.builder.gt(x, IRLiteral(upper_bound)))
        self.builder.assert_(ok)

        return self.builder.exp(x, y)

    def _clamp_basetype(self, val: IROperand, typ) -> IROperand:
        """Clamp value to type bounds."""
        lo, hi = typ.int_bounds

        if typ.is_signed:
            ge_lo = self.builder.iszero(self.builder.slt(val, IRLiteral(lo)))
            le_hi = self.builder.iszero(self.builder.sgt(val, IRLiteral(hi)))
            ok = self.builder.and_(ge_lo, le_hi)
        else:
            ok = self.builder.iszero(self.builder.gt(val, IRLiteral(hi)))

        self.builder.assert_(ok)
        return val

    # === Control Flow Statements ===

    def lower_If(self) -> None:
        """Lower if/elif/else statement."""
        node = self.node

        # Evaluate condition in current block
        cond = Expr(node.test, self.ctx).lower()
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

        # Create exit/merge block
        exit_block = self.builder.create_block("if_exit")
        self.builder.append_block(exit_block)
        self.builder.set_block(exit_block)

        # Add jumps from finish blocks if not terminated
        if not then_block_finish.is_terminated:
            then_block_finish.append_instruction("jmp", exit_block.label)
        if not else_block_finish.is_terminated:
            else_block_finish.append_instruction("jmp", exit_block.label)

    def _lower_body(self, stmts: list) -> None:
        """Lower a list of statements."""
        for stmt in stmts:
            Stmt(stmt, self.ctx).lower()

    # === For Loop Statements ===

    def lower_For(self) -> None:
        """Lower for loop - dispatches to range or iter loop."""
        node = self.node
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
        target_type = node.target.target._metadata["type"]
        varname = node.target.target.id

        # Parse range arguments
        range_call = node.iter
        args = range_call.args

        if len(args) == 1:
            start = IRLiteral(0)
            end_expr = Expr(args[0], self.ctx).lower()
        else:
            start = Expr(args[0], self.ctx).lower()
            end_expr = Expr(args[1], self.ctx).lower()

        # Handle bound kwarg for dynamic ranges
        kwargs = {kw.arg: kw.value for kw in range_call.keywords}
        has_bound = "bound" in kwargs

        if has_bound:
            # Dynamic range: compute rounds = end - start
            # The bound check will catch if rounds > bound (including negative/underflow)
            rounds_bound = kwargs["bound"].value  # literal int value
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
        counter_ptr = self.ctx.new_variable(varname, target_type, mutable=False)
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

        # Bound check: assert rounds <= rounds_bound
        if has_bound:
            # assert iszero(gt(rounds, rounds_bound))
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
            self.builder.mstore(counter_var, counter_ptr)
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
        target_type = node.target.target._metadata["type"]
        varname = node.target.target.id

        # Evaluate array expression
        array = Expr(node.iter, self.ctx).lower()
        array_typ = node.iter._metadata["type"]

        # Get length and bound
        if isinstance(array_typ, DArrayT):
            # Dynamic array: length is first word
            length = self.builder.mload(array)
            bound = array_typ.count
        elif isinstance(array_typ, SArrayT):
            # Static array: length is compile-time constant
            length = IRLiteral(array_typ.count)
            bound = array_typ.count
        else:
            raise CompilerPanic(f"Cannot iterate over type: {array_typ}")

        # Element size
        elem_size = array_typ.value_type.memory_bytes_required

        # Allocate loop variable (copy of element, not reference)
        item_ptr = self.ctx.new_variable(varname, target_type, mutable=False)
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
            # For DArrayT, offset = 32 (skip length word)
            # For SArrayT, offset = 0
            offset_base = 32 if isinstance(array_typ, DArrayT) else 0
            index_offset = self.builder.mul(index_var, IRLiteral(elem_size))
            if offset_base > 0:
                total_offset = self.builder.add(IRLiteral(offset_base), index_offset)
            else:
                total_offset = index_offset
            elem_addr = self.builder.add(array, total_offset)

            # Copy element to loop variable
            if elem_size <= 32:
                # Single word: simple load/store
                val = self.builder.mload(elem_addr)
                self.builder.mstore(val, item_ptr)
            else:
                # Multi-word: use mcopy (size, src, dst)
                self.builder.mcopy(IRLiteral(elem_size), elem_addr, item_ptr)

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

    def lower_Return(self) -> None:
        """Lower return statement.

        For internal functions: loads return values to buffer, then ret to return_pc.
        For external functions: handled separately (ABI encoding).
        """
        node = self.node
        func_t = self.ctx.func_t

        if func_t is None:
            raise CompilerPanic("Return outside function")

        returns_count = self.ctx.returns_stack_count(func_t)

        if node.value is None:
            # No return value - just return
            if self.ctx.return_pc is not None:
                self.builder.ret(self.ctx.return_pc)
            return

        # Evaluate return expression
        ret_val = Expr(node.value, self.ctx).lower()

        # Store return value(s) to return buffer
        if returns_count > 0 and self.ctx.return_buffer is not None:
            # Multi-return via stack: store to buffer, then load and ret
            buf = self.ctx.return_buffer

            # For tuple returns, need to unpack
            ret_typ = func_t.return_type
            if self.ctx.returns_stack_count(func_t) > 1 and hasattr(ret_typ, "tuple_items"):
                # Tuple return - value should be a memory pointer
                for i, (_k, elem_t) in enumerate(ret_typ.tuple_items()):
                    if isinstance(ret_val, IRLiteral):
                        src_ptr = IRLiteral(ret_val.value + i * 32)
                    else:
                        src_ptr = self.builder.add(ret_val, IRLiteral(i * 32))
                    val = self.builder.mload(src_ptr)
                    if i == 0:
                        dst_ptr = buf
                    else:
                        dst_ptr = self.builder.add(buf, IRLiteral(i * 32))
                    self.builder.mstore(val, dst_ptr)
            else:
                # Single value return
                self.builder.mstore(ret_val, buf)

            # Now load from buffer and ret
            ret_vals = []
            for i in range(returns_count):
                if i == 0:
                    ptr = buf
                else:
                    ptr = self.builder.add(buf, IRLiteral(i * 32))
                ret_vals.append(self.builder.mload(ptr))

            self.builder.ret(*ret_vals, self.ctx.return_pc)
        elif self.ctx.return_buffer is not None:
            # Memory return - store to buffer, caller reads it
            ret_typ = func_t.return_type
            self.ctx.store_memory(ret_val, self.ctx.return_buffer, ret_typ)
            self.builder.ret(self.ctx.return_pc)
        else:
            # External function return - defer to later task
            raise CompilerPanic("External function return not yet implemented")
