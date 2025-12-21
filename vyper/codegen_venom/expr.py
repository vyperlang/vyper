"""
Lower Vyper AST expressions to Venom IR.

This module handles the first stage of expression codegen: converting
Vyper AST literal and expression nodes into Venom IR operands.
"""
from vyper import ast as vy_ast
from vyper.codegen.arithmetic import calculate_largest_base, calculate_largest_power
from vyper.exceptions import CompilerPanic, TypeCheckFailure
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DecimalT,
    IntegerT,
    StringT,
)
from vyper.semantics.types.user import FlagT
from vyper.utils import DECIMAL_DIVISOR, ceil32
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

from .context import VenomCodegenContext


class Expr:
    """Lower Vyper expressions to Venom IR."""

    def __init__(self, node: vy_ast.VyperNode, ctx: VenomCodegenContext):
        self.node = node.reduced()
        self.ctx = ctx
        self.builder = ctx.builder

    def lower(self) -> IROperand:
        """Dispatch to type-specific lowering method."""
        fn_name = f"lower_{type(self.node).__name__}"
        method = getattr(self, fn_name, None)
        if method is None:
            raise CompilerPanic(f"Unsupported expr: {type(self.node)}")
        return method()

    # === Literal Lowering ===

    def lower_Int(self) -> IRLiteral:
        """Lower integer literal."""
        return IRLiteral(self.node.value)

    def lower_Decimal(self) -> IRLiteral:
        """Lower decimal literal.

        Decimals are stored as fixed-point integers scaled by DECIMAL_DIVISOR (10^10).
        """
        val = self.node.value * DECIMAL_DIVISOR
        return IRLiteral(int(val))

    def lower_Hex(self) -> IRLiteral:
        """Lower hex literal (address or bytesN).

        For addresses: direct int conversion.
        For bytesN: left-padded (shifted left) to align in 32-byte word.
        """
        hexstr = self.node.value
        t = self.node._metadata["type"]

        if t == AddressT():
            return IRLiteral(int(hexstr, 16))

        elif isinstance(t, BytesM_T):
            n_bytes = (len(hexstr) - 2) // 2
            # Left-pad: shift value to occupy high bytes of 32-byte word
            val = int(hexstr, 16) << 8 * (32 - n_bytes)
            return IRLiteral(val)

        raise CompilerPanic(f"Unsupported Hex literal type: {t}")

    def lower_NameConstant(self) -> IRLiteral:
        """Lower True/False constants."""
        assert isinstance(self.node.value, bool)
        return IRLiteral(int(self.node.value))

    # === Bytelike Literals ===

    def lower_Bytes(self) -> IRVariable:
        """Lower bytes literal (b'...')."""
        return self._lower_bytelike(BytesT, self.node.value)

    def lower_HexBytes(self) -> IRVariable:
        """Lower hex bytes literal (x'...')."""
        assert isinstance(self.node.value, bytes)
        return self._lower_bytelike(BytesT, self.node.value)

    def lower_Str(self) -> IRVariable:
        """Lower string literal ('...')."""
        bytez = self.node.value.encode("utf-8")
        return self._lower_bytelike(StringT, bytez)

    def _lower_bytelike(self, typeclass: type, bytez: bytes) -> IRVariable:
        """Allocate memory and store bytes/string literal.

        Memory layout:
            ptr+0:  length (32 bytes)
            ptr+32: data[0:32] (right-padded with zeros)
            ptr+64: data[32:64] (if needed)
            ...

        Returns pointer to allocated memory.
        """
        bytez_length = len(bytez)
        btype = typeclass(bytez_length)

        # Allocate memory for length word + data
        ptr = self.ctx.new_internal_variable(btype)

        # Store length at ptr
        self.builder.mstore(IRLiteral(bytez_length), ptr)

        # Store data in 32-byte chunks, right-padded with zeros
        for i in range(0, bytez_length, 32):
            chunk = (bytez + b"\x00" * 31)[i : i + 32]
            word = int.from_bytes(chunk, "big")
            offset = self.builder.add(ptr, IRLiteral(32 + i))
            self.builder.mstore(IRLiteral(word), offset)

        return ptr

    # === Binary Operations ===

    def lower_BinOp(self) -> IRVariable:
        """Lower binary operations with appropriate overflow checking."""
        node = self.node
        left = Expr(node.left, self.ctx).lower()
        right = Expr(node.right, self.ctx).lower()
        op = node.op
        typ = node.left._metadata["type"]

        # Bitwise operations - no overflow checks needed
        if isinstance(op, vy_ast.BitAnd):
            return self.builder.and_(left, right)
        if isinstance(op, vy_ast.BitOr):
            return self.builder.or_(left, right)
        if isinstance(op, vy_ast.BitXor):
            return self.builder.xor(left, right)

        # Shift operations - only 256-bit types allowed
        if isinstance(op, vy_ast.LShift):
            if not isinstance(typ, IntegerT) or typ.bits != 256:
                raise CompilerPanic("Shift operations require 256-bit types")
            # shl(bits, value) - operand order is (bits, value)
            return self.builder.shl(right, left)

        if isinstance(op, vy_ast.RShift):
            if not isinstance(typ, IntegerT) or typ.bits != 256:
                raise CompilerPanic("Shift operations require 256-bit types")
            if typ.is_signed:
                return self.builder.sar(right, left)
            else:
                return self.builder.shr(right, left)

        # Arithmetic operations with overflow checks
        if isinstance(op, vy_ast.Add):
            return self._safe_add(left, right, typ)

        if isinstance(op, vy_ast.Sub):
            return self._safe_sub(left, right, typ)

        if isinstance(op, vy_ast.Mult):
            return self._safe_mul(left, right, typ, node)

        if isinstance(op, vy_ast.Div):
            return self._safe_div(left, right, typ, node)

        if isinstance(op, vy_ast.FloorDiv):
            return self._safe_floordiv(left, right, typ, node)

        if isinstance(op, vy_ast.Mod):
            return self._safe_mod(left, right, typ)

        if isinstance(op, vy_ast.Pow):
            return self._safe_pow(left, right, typ, node)

        raise CompilerPanic(f"Unsupported BinOp: {type(op)}")

    def _safe_add(self, x: IROperand, y: IROperand, typ) -> IRVariable:
        """Add with overflow checking."""
        res = self.builder.add(x, y)

        if isinstance(typ, (IntegerT, DecimalT)) and typ.bits < 256:
            return self._clamp_basetype(res, typ)

        # 256-bit overflow check
        if isinstance(typ, (IntegerT, DecimalT)):
            if typ.is_signed:
                # (y < 0) == (res < x)
                y_neg = self.builder.slt(y, IRLiteral(0))
                res_lt_x = self.builder.slt(res, x)
                ok = self.builder.eq(y_neg, res_lt_x)
            else:
                # res >= x
                ok = self.builder.iszero(self.builder.lt(res, x))
            self.builder.assert_(ok)

        return res

    def _safe_sub(self, x: IROperand, y: IROperand, typ) -> IRVariable:
        """Subtract with overflow checking."""
        res = self.builder.sub(x, y)

        if isinstance(typ, (IntegerT, DecimalT)) and typ.bits < 256:
            return self._clamp_basetype(res, typ)

        # 256-bit overflow check
        if isinstance(typ, (IntegerT, DecimalT)):
            if typ.is_signed:
                # (y < 0) == (res > x)
                y_neg = self.builder.slt(y, IRLiteral(0))
                res_gt_x = self.builder.sgt(res, x)
                ok = self.builder.eq(y_neg, res_gt_x)
            else:
                # res <= x
                ok = self.builder.iszero(self.builder.gt(res, x))
            self.builder.assert_(ok)

        return res

    def _safe_mul(
        self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp
    ) -> IRVariable:
        """Multiply with overflow checking."""
        res = self.builder.mul(x, y)

        if isinstance(typ, (IntegerT, DecimalT)):
            is_signed = typ.is_signed

            if typ.bits > 128:
                # Check overflow mod 256: (res / y == x) OR (y == 0)
                DIV = self.builder.sdiv if is_signed else self.builder.div
                div_check = self.builder.eq(DIV(res, y), x)
                y_zero = self.builder.iszero(y)
                ok = self.builder.or_(div_check, y_zero)

                # int256 special case: not (x == -2^255 and y == -1)
                if is_signed and typ.bits == 256:
                    min_int = 1 << 255  # -2^255 in two's complement
                    x_is_min = self.builder.eq(x, IRLiteral(min_int))
                    y_is_neg1 = self.builder.iszero(self.builder.not_(y))
                    special_case = self.builder.and_(x_is_min, y_is_neg1)
                    not_special = self.builder.iszero(special_case)
                    ok = self.builder.and_(ok, not_special)

                self.builder.assert_(ok)

            # For decimals, divide result by divisor
            if isinstance(typ, DecimalT):
                DIV = self.builder.sdiv if is_signed else self.builder.div
                res = DIV(res, IRLiteral(typ.divisor))

            # Clamp result if needed
            if typ.bits < 256 or isinstance(typ, DecimalT):
                res = self._clamp_basetype(res, typ)

        return res

    def _safe_div(
        self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp
    ) -> IRVariable:
        """Decimal division with overflow checking."""
        if not isinstance(typ, DecimalT):
            raise CompilerPanic("/ operator only valid for decimals")

        # Multiply numerator by divisor first
        x_scaled = self.builder.mul(x, IRLiteral(typ.divisor))

        # Clamp divisor > 0 for unsigned, or use sgt for signed
        if typ.is_signed:
            y_gt_zero = self.builder.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = self.builder.gt(y, IRLiteral(0))
        self.builder.assert_(y_gt_zero)

        DIV = self.builder.sdiv if typ.is_signed else self.builder.div
        res = DIV(x_scaled, y)

        # Always clamp decimals
        return self._clamp_basetype(res, typ)

    def _safe_floordiv(
        self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp
    ) -> IRVariable:
        """Integer floor division with overflow checking."""
        if not isinstance(typ, IntegerT):
            raise CompilerPanic("// operator only valid for integers")

        is_signed = typ.is_signed

        # Clamp divisor > 0
        if is_signed:
            y_gt_zero = self.builder.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = self.builder.gt(y, IRLiteral(0))
        self.builder.assert_(y_gt_zero)

        DIV = self.builder.sdiv if is_signed else self.builder.div
        res = DIV(x, y)

        # int256: check not (x == -2^255 and y == -1)
        if is_signed and typ.bits == 256:
            min_int = 1 << 255
            x_is_min = self.builder.eq(x, IRLiteral(min_int))
            y_is_neg1 = self.builder.iszero(self.builder.not_(y))
            special_case = self.builder.and_(x_is_min, y_is_neg1)
            ok = self.builder.iszero(special_case)
            self.builder.assert_(ok)
        elif is_signed and typ.bits < 256:
            # For smaller signed types, clamp result
            res = self._clamp_basetype(res, typ)

        return res

    def _safe_mod(self, x: IROperand, y: IROperand, typ) -> IRVariable:
        """Modulo with divisor check."""
        if not isinstance(typ, IntegerT):
            raise CompilerPanic("% operator only valid for integers")

        is_signed = typ.is_signed

        # Clamp divisor > 0
        if is_signed:
            y_gt_zero = self.builder.sgt(y, IRLiteral(0))
        else:
            y_gt_zero = self.builder.gt(y, IRLiteral(0))
        self.builder.assert_(y_gt_zero)

        MOD = self.builder.smod if is_signed else self.builder.mod
        return MOD(x, y)

    def _safe_pow(
        self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp
    ) -> IRVariable:
        """Exponentiation with bounds checking.

        Requires at least one operand to be a literal for bounds computation.
        """
        if not isinstance(typ, IntegerT):
            raise TypeCheckFailure("pow only valid for integers")

        is_signed = typ.is_signed
        bits = typ.bits

        # Get the reduced nodes to check for literals
        left_node = node.left.reduced()
        right_node = node.right.reduced()

        if isinstance(left_node, vy_ast.Int):
            # Base is literal - compute max exponent at compile time
            base_val = left_node.value
            if base_val in (-1, 0, 1):
                # For special bases, just need y >= 0 for signed
                if is_signed:
                    # sge(y, 0) = iszero(slt(y, 0))
                    ok = self.builder.iszero(self.builder.slt(y, IRLiteral(0)))
                else:
                    ok = IRLiteral(1)  # always ok for unsigned
            else:
                upper_bound = calculate_largest_power(base_val, bits, is_signed)
                ok = self.builder.iszero(self.builder.gt(y, IRLiteral(upper_bound)))
            self.builder.assert_(ok)

        elif isinstance(right_node, vy_ast.Int):
            # Exponent is literal - compute max base at compile time
            exp_val = right_node.value
            if exp_val in (0, 1):
                ok = IRLiteral(1)  # always ok
            else:
                lower_bound, upper_bound = calculate_largest_base(exp_val, bits, is_signed)
                if is_signed:
                    # sge(x, lower_bound) = iszero(slt(x, lower_bound))
                    ge_lower = self.builder.iszero(self.builder.slt(x, IRLiteral(lower_bound)))
                    le_upper = self.builder.iszero(self.builder.sgt(x, IRLiteral(upper_bound)))
                    ok = self.builder.and_(ge_lower, le_upper)
                else:
                    ok = self.builder.iszero(self.builder.gt(x, IRLiteral(upper_bound)))
            self.builder.assert_(ok)

        else:
            # Neither operand is literal - not currently supported
            raise TypeCheckFailure("pow requires at least one literal operand")

        return self.builder.exp(x, y)

    def _clamp_basetype(self, val: IRVariable, typ) -> IRVariable:
        """Clamp value to type bounds."""
        lo, hi = typ.int_bounds

        if typ.is_signed:
            # signed: lo <= val <= hi
            # sge(val, lo) = iszero(slt(val, lo))
            ge_lo = self.builder.iszero(self.builder.slt(val, IRLiteral(lo)))
            le_hi = self.builder.iszero(self.builder.sgt(val, IRLiteral(hi)))
            ok = self.builder.and_(ge_lo, le_hi)
        else:
            # unsigned: 0 <= val <= hi (val is always >= 0 in unsigned)
            ok = self.builder.iszero(self.builder.gt(val, IRLiteral(hi)))

        self.builder.assert_(ok)
        return val

    # === Unary Operations ===

    def lower_UnaryOp(self) -> IRVariable:
        """Lower unary operations."""
        node = self.node
        operand = Expr(node.operand, self.ctx).lower()
        typ = node.operand._metadata["type"]
        op = node.op

        if isinstance(op, vy_ast.Not):
            # Boolean NOT
            if not isinstance(typ, BoolT):
                raise CompilerPanic("Not operator only valid for bool")
            return self.builder.iszero(operand)

        if isinstance(op, vy_ast.Invert):
            # Bitwise NOT (~x)
            if isinstance(typ, FlagT):
                # For flags: xor with mask of all valid flag bits
                n_members = len(typ._flag_members)
                mask = (1 << n_members) - 1
                return self.builder.xor(operand, IRLiteral(mask))
            elif isinstance(typ, IntegerT) and typ.bits == 256 and not typ.is_signed:
                # For uint256: full bitwise not
                return self.builder.not_(operand)
            elif isinstance(typ, BytesM_T) and typ.m == 32:
                # For bytes32: full bitwise not
                return self.builder.not_(operand)
            else:
                raise CompilerPanic(f"Invert not supported for type {typ}")

        if isinstance(op, vy_ast.USub):
            # Unary minus (-x) - only for signed integers
            if not isinstance(typ, (IntegerT, DecimalT)):
                raise CompilerPanic("USub only valid for numeric types")
            if not typ.is_signed:
                raise CompilerPanic("USub only valid for signed types")

            # Check operand > min_int to prevent negating MIN_INT
            min_int_val, _ = typ.int_bounds
            ok = self.builder.sgt(operand, IRLiteral(min_int_val))
            self.builder.assert_(ok)

            return self.builder.sub(IRLiteral(0), operand)

        raise CompilerPanic(f"Unsupported UnaryOp: {type(op)}")
