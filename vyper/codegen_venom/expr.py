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
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.shortcuts import BYTES32_T
from vyper.semantics.types.user import FlagT
from vyper.utils import DECIMAL_DIVISOR, ceil32
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

from .context import VenomCodegenContext

# Environment variable prefixes for attribute access
ENVIRONMENT_VARIABLES = {"block", "msg", "tx", "chain"}


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

    # === Comparison Operations ===

    def lower_Compare(self) -> IRVariable:
        """Lower comparison operations.

        Comparisons: <, <=, >, >=, ==, !=
        Membership: in, not in (for flags)

        Note: Array membership (in/not in for arrays) is handled separately
        and requires loops, which will be implemented with control flow.
        """
        node = self.node
        left = Expr(node.left, self.ctx).lower()
        right = Expr(node.right, self.ctx).lower()
        op = node.op
        left_typ = node.left._metadata["type"]
        right_typ = node.right._metadata["type"]

        # Membership tests for Flag types
        if isinstance(op, (vy_ast.In, vy_ast.NotIn)):
            if isinstance(right_typ, FlagT):
                # x in flags: check if (x & flags) != 0
                # x not in flags: check if (x & flags) == 0
                intersection = self.builder.and_(left, right)
                if isinstance(op, vy_ast.In):
                    # iszero(iszero(x)) = 1 if x != 0
                    return self.builder.iszero(self.builder.iszero(intersection))
                else:  # NotIn
                    return self.builder.iszero(intersection)
            else:
                # Array membership requires loops - not yet implemented
                raise CompilerPanic("Array membership not yet implemented")

        # Determine if we need signed or unsigned comparison
        # UINT256 uses unsigned comparisons; all other types use signed
        use_unsigned = (
            left_typ == UINT256_T
            and right_typ == UINT256_T
        )

        # Dispatch to appropriate comparison
        if isinstance(op, vy_ast.Lt):
            if use_unsigned:
                return self.builder.lt(left, right)
            return self.builder.slt(left, right)

        if isinstance(op, vy_ast.Gt):
            if use_unsigned:
                return self.builder.gt(left, right)
            return self.builder.sgt(left, right)

        if isinstance(op, vy_ast.Eq):
            return self.builder.eq(left, right)

        if isinstance(op, vy_ast.NotEq):
            # ne = iszero(eq)
            return self.builder.iszero(self.builder.eq(left, right))

        if isinstance(op, vy_ast.LtE):
            # le = iszero(gt)
            if use_unsigned:
                return self.builder.iszero(self.builder.gt(left, right))
            return self.builder.iszero(self.builder.sgt(left, right))

        if isinstance(op, vy_ast.GtE):
            # ge = iszero(lt)
            if use_unsigned:
                return self.builder.iszero(self.builder.lt(left, right))
            return self.builder.iszero(self.builder.slt(left, right))

        raise CompilerPanic(f"Unsupported comparison op: {type(op)}")

    # === Boolean Operations ===

    def lower_BoolOp(self) -> IRVariable:
        """Lower boolean operations with short-circuit evaluation.

        And: if a is false, skip evaluation of remaining operands
        Or: if a is true, skip evaluation of remaining operands

        Uses control flow blocks to implement short-circuit:
        - And: chain of conditional jumps, false branch short-circuits to 0
        - Or: chain of conditional jumps, true branch short-circuits to 1
        """
        node = self.node
        op = node.op
        values = node.values

        assert len(values) >= 2, "BoolOp needs at least 2 operands"

        # Pre-allocate result variable
        result = self.builder.new_variable()
        exit_bb = self.builder.create_block("bool_exit")

        if isinstance(op, vy_ast.And):
            # a and b and c:
            # evaluate a, if false -> result=0, jump to exit
            # evaluate b, if false -> result=0, jump to exit
            # ...
            # evaluate last, result = last value, jump to exit
            for val in values[:-1]:
                cond = Expr(val, self.ctx).lower()
                next_bb = self.builder.create_block("and_next")
                false_bb = self.builder.create_block("and_false")

                self.builder.jnz(cond, next_bb.label, false_bb.label)

                # false branch: result = 0, jump to exit
                self.builder.append_block(false_bb)
                self.builder.set_block(false_bb)
                self.builder.assign_to(IRLiteral(0), result)
                self.builder.jmp(exit_bb.label)

                # continue with next check
                self.builder.append_block(next_bb)
                self.builder.set_block(next_bb)

            # Last value: result = value, jump to exit
            last_val = Expr(values[-1], self.ctx).lower()
            self.builder.assign_to(last_val, result)
            self.builder.jmp(exit_bb.label)

        elif isinstance(op, vy_ast.Or):
            # a or b or c:
            # evaluate a, if true -> result=1, jump to exit
            # evaluate b, if true -> result=1, jump to exit
            # ...
            # evaluate last, result = last value, jump to exit
            for val in values[:-1]:
                cond = Expr(val, self.ctx).lower()
                true_bb = self.builder.create_block("or_true")
                next_bb = self.builder.create_block("or_next")

                self.builder.jnz(cond, true_bb.label, next_bb.label)

                # true branch: result = 1, jump to exit
                self.builder.append_block(true_bb)
                self.builder.set_block(true_bb)
                self.builder.assign_to(IRLiteral(1), result)
                self.builder.jmp(exit_bb.label)

                # continue with next check
                self.builder.append_block(next_bb)
                self.builder.set_block(next_bb)

            # Last value: result = value, jump to exit
            last_val = Expr(values[-1], self.ctx).lower()
            self.builder.assign_to(last_val, result)
            self.builder.jmp(exit_bb.label)

        else:
            raise CompilerPanic(f"Unsupported BoolOp: {type(op)}")

        # Continue from exit block
        self.builder.append_block(exit_bb)
        self.builder.set_block(exit_bb)

        return result

    # === Variable and Name Operations ===

    def lower_Name(self) -> IROperand:
        """Lower name reference.

        Handles:
        - `self` keyword -> address opcode
        - Local variables (params, locals) -> mload from memory pointer
        - Module constants -> evaluate constant expression
        - Immutables -> iload or mload depending on context
        """
        varname = self.node.id

        # Case 1: "self" keyword -> address opcode
        if varname == "self":
            return self.builder.address()

        # Get variable info from semantic analysis
        varinfo = self.node._expr_info.var_info
        assert varinfo is not None

        # Case 2: Local variable in context.variables
        if varname in self.ctx.variables:
            ptr = self.ctx.lookup_ptr(varname)
            return self.builder.mload(ptr)

        # Case 3: Module constant - recursively lower the constant's value
        if varinfo.is_constant:
            return Expr(varinfo.decl_node.value, self.ctx).lower()

        # Case 4: Immutable - load from code or memory depending on context
        if varinfo.is_immutable:
            # In constructor: immutables are in memory (being written)
            # After deploy: immutables are in code (read via iload)
            if self.ctx.is_ctor_context:
                # During constructor, immutable is in memory at varinfo.position
                return self.builder.mload(IRLiteral(varinfo.position.position))
            else:
                # After deployment, use iload to read from deployed code
                return self.builder.iload(IRLiteral(varinfo.position.position))

        raise CompilerPanic(f"Unknown variable: {varname}")

    def lower_Attribute(self) -> IROperand:
        """Lower attribute access.

        Handles:
        - Flag constants (MyFlag.VALUE)
        - Address properties (.balance, .codesize, .codehash, etc.)
        - Environment variables (msg.sender, block.timestamp, etc.)
        - State variables (self.x)
        - Struct fields (x.field)
        - Interface address (x.address)
        """
        typ = self.node._metadata["type"]

        # Case 1: Flag constants (MyFlag.VALUE)
        if isinstance(typ, FlagT):
            from vyper.semantics.types.utils import type_from_annotation
            value_typ = self.node.value._metadata.get("type")
            # Check if this is a flag type access (e.g., MyFlag.VALUE)
            if hasattr(value_typ, "_flag_members"):
                flag_id = typ._flag_members[self.node.attr]
                value = 2**flag_id  # 0 => 1, 1 => 2, 2 => 4, etc.
                return IRLiteral(value)

        # Case 2: Address properties
        attr = self.node.attr
        if attr == "balance":
            sub = Expr(self.node.value, self.ctx).lower()
            # Check if it's self.balance
            if isinstance(self.node.value, vy_ast.Name) and self.node.value.id == "self":
                return self.builder.selfbalance()
            return self.builder.balance(sub)

        if attr == "codesize":
            if isinstance(self.node.value, vy_ast.Name) and self.node.value.id == "self":
                return self.builder.codesize()
            sub = Expr(self.node.value, self.ctx).lower()
            return self.builder.extcodesize(sub)

        if attr == "is_contract":
            sub = Expr(self.node.value, self.ctx).lower()
            codesize = self.builder.extcodesize(sub)
            return self.builder.gt(codesize, IRLiteral(0))

        if attr == "codehash":
            sub = Expr(self.node.value, self.ctx).lower()
            return self.builder.extcodehash(sub)

        # Case 3: Environment variables (msg.*, block.*, tx.*, chain.*)
        if isinstance(self.node.value, vy_ast.Name) and self.node.value.id in ENVIRONMENT_VARIABLES:
            return self._lower_environment_attr()

        # Case 4: State variables (self.x)
        varinfo = self.node._expr_info.var_info
        if varinfo is not None:
            # Constant state variable - evaluate the constant expression
            if varinfo.is_constant:
                return Expr(varinfo.decl_node.value, self.ctx).lower()

            # Immutable state variable
            if varinfo.is_immutable:
                if self.ctx.is_ctor_context:
                    return self.builder.mload(IRLiteral(varinfo.position.position))
                else:
                    return self.builder.iload(IRLiteral(varinfo.position.position))

            # Regular storage variable - return sload of storage slot
            # Note: This is simplified for word-sized values. Complex types
            # need pointer handling which will be done in later tasks.
            slot = varinfo.position.position
            return self.builder.sload(IRLiteral(slot))

        # Case 5: Interface address (x.address where x is an interface)
        from vyper.semantics.types import InterfaceT
        sub = Expr(self.node.value, self.ctx).lower()
        sub_typ = self.node.value._metadata.get("type")
        if isinstance(sub_typ, InterfaceT) and attr == "address":
            return sub

        # Case 6: Struct field access - defer to later tasks
        raise CompilerPanic(f"Unsupported attribute access: {self.node.attr}")

    def _lower_environment_attr(self) -> IROperand:
        """Lower environment variable attributes (msg.*, block.*, tx.*, chain.*)."""
        key = f"{self.node.value.id}.{self.node.attr}"

        # msg.* attributes
        if key == "msg.sender":
            return self.builder.caller()
        if key == "msg.value":
            # Note: payability check should be done at a higher level
            return self.builder.callvalue()
        if key in ("msg.gas", "msg.mana"):
            return self.builder.gas()
        if key == "msg.data":
            # Adhoc node - replaced in Slice/Len. Return calldatasize for now.
            raise CompilerPanic("msg.data requires Slice/Len context")

        # block.* attributes
        if key == "block.timestamp":
            return self.builder.timestamp()
        if key == "block.number":
            return self.builder.number()
        if key == "block.coinbase":
            return self.builder.coinbase()
        if key == "block.gaslimit":
            return self.builder.gaslimit()
        if key == "block.basefee":
            return self.builder.basefee()
        if key == "block.blobbasefee":
            # Note: EVM version check should be done at a higher level
            return self.builder.blobbasefee()
        if key == "block.prevrandao":
            return self.builder.prevrandao()
        if key == "block.difficulty":
            # Pre-Paris alias for prevrandao
            return self.builder.prevrandao()
        if key == "block.prevhash":
            # blockhash(number - 1)
            num = self.builder.number()
            prev_num = self.builder.sub(num, IRLiteral(1))
            return self.builder.blockhash(prev_num)

        # tx.* attributes
        if key == "tx.origin":
            return self.builder.origin()
        if key == "tx.gasprice":
            return self.builder.gasprice()

        # chain.* attributes
        if key == "chain.id":
            return self.builder.chainid()

        raise CompilerPanic(f"Unknown environment variable: {key}")
