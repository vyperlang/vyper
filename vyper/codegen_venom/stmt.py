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
from vyper.venom.basicblock import IRLiteral, IROperand

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

        # Get the destination pointer
        dst_ptr = self._get_target_ptr(target)

        # For primitive word types, no overlap concern - just store
        if target_typ._is_prim_word:
            self._store_value(dst_ptr, src, target_typ)
        else:
            # Multi-word types need overlap detection - defer to later tasks
            raise CompilerPanic("Complex type assignment not yet implemented")

    def lower_AugAssign(self) -> None:
        """Lower augmented assignment.

        Example: `x += 5` or `self.x *= 2`

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

        # Get target pointer and load current value
        dst_ptr = self._get_target_ptr(target)
        left = self._load_value(dst_ptr, target_typ)

        # Evaluate the RHS
        right = Expr(right_node, self.ctx).lower()

        # Apply the operation
        result = self._apply_augassign_op(op, left, right, target_typ, right_node)

        # Store result back
        self._store_value(dst_ptr, result, target_typ)

    # === Helper Methods ===

    def _get_target_ptr(self, target: vy_ast.VyperNode) -> IROperand:
        """Get pointer to assignment target.

        Handles:
        - Name: local variable or state variable
        - Subscript: array/mapping access (deferred)
        - Attribute: struct field or state variable (self.x)
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
                # Storage variable
                if not varinfo.is_constant and not varinfo.is_immutable:
                    # Return storage slot as the "pointer"
                    # For storage, we use sstore(slot, value) directly
                    return IRLiteral(varinfo.position.position)

                # Immutable in constructor context
                if varinfo.is_immutable and self.ctx.is_ctor_context:
                    return IRLiteral(varinfo.position.position)

                if varinfo.is_constant:
                    raise TypeCheckFailure("Cannot assign to constant")
                if varinfo.is_immutable:
                    raise TypeCheckFailure("Cannot assign to immutable outside constructor")

            raise CompilerPanic(f"Unsupported attribute target: {target.attr}")

        elif isinstance(target, vy_ast.Subscript):
            # x[i] = ... (array/mapping access) - defer to later tasks
            raise CompilerPanic("Subscript assignment not yet implemented")

        raise CompilerPanic(f"Unsupported assignment target: {type(target)}")

    def _load_value(self, ptr: IROperand, typ) -> IROperand:
        """Load a value from a pointer based on type context."""
        # Check if this is a storage slot (IRLiteral) or memory pointer (IRVariable)
        if isinstance(ptr, IRLiteral):
            # Storage/transient variable - use sload
            # TODO: Support transient storage
            return self.builder.sload(ptr)
        else:
            # Memory variable - use mload
            return self.builder.mload(ptr)

    def _store_value(self, ptr: IROperand, val: IROperand, typ) -> None:
        """Store a value to a pointer based on type context."""
        # Check if this is a storage slot (IRLiteral) or memory pointer (IRVariable)
        if isinstance(ptr, IRLiteral):
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
