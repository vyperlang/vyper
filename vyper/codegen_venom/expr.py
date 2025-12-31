"""
Lower Vyper AST expressions to Venom IR.

This module handles the first stage of expression codegen: converting
Vyper AST literal and expression nodes into Venom IR operands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from vyper.codegen_venom.arithmetic import (
    clamp_basetype,
    safe_add,
    safe_div,
    safe_floordiv,
    safe_mod,
    safe_mul,
    safe_pow,
    safe_sub,
)

import vyper.utils as util
from vyper import ast as vy_ast
from vyper.builtins._signatures import BuiltinFunctionT
from vyper.codegen.core import (
    DYNAMIC_ARRAY_OVERHEAD,
    calculate_type_for_external_return,
    get_type_for_exact_size,
    needs_external_call_wrap,
)
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DecimalT,
    IntegerT,
    InterfaceT,
    StringT,
    TupleT,
    is_type_t,
)
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT, StateMutability
from vyper.semantics.types.subscriptable import DArrayT, HashMapT, SArrayT
from vyper.semantics.types.shortcuts import BYTES32_T, UINT256_T
from vyper.semantics.types.user import FlagT, StructT
from vyper.utils import DECIMAL_DIVISOR, MemoryPositions
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

from .context import VenomCodegenContext


@dataclass
class _CallKwargs:
    """Keyword arguments for external calls."""

    value: IROperand  # ETH value to send (CALL only)
    gas: IROperand  # Gas limit for the call
    skip_contract_check: bool  # Skip extcodesize check
    default_return_value: Optional[IROperand]  # Default if returndatasize==0


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
        node = self.node
        assert isinstance(node, vy_ast.Int)
        return IRLiteral(node.value)

    def lower_Decimal(self) -> IRLiteral:
        """Lower decimal literal.

        Decimals are stored as fixed-point integers scaled by DECIMAL_DIVISOR (10^10).
        """
        node = self.node
        assert isinstance(node, vy_ast.Decimal)
        val = node.value * DECIMAL_DIVISOR
        return IRLiteral(int(val))

    def lower_Hex(self) -> IRLiteral:
        """Lower hex literal (address or bytesN).

        For addresses: direct int conversion.
        For bytesN: left-padded (shifted left) to align in 32-byte word.
        """
        node = self.node
        assert isinstance(node, vy_ast.Hex)
        hexstr = node.value
        t = node._metadata["type"]

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
        node = self.node
        assert isinstance(node, vy_ast.NameConstant)
        assert isinstance(node.value, bool)
        return IRLiteral(int(node.value))

    # === Bytelike Literals ===

    def lower_Bytes(self) -> IRVariable:
        """Lower bytes literal (b'...')."""
        node = self.node
        assert isinstance(node, vy_ast.Bytes)
        return self._lower_bytelike(BytesT, node.value)

    def lower_HexBytes(self) -> IRVariable:
        """Lower hex bytes literal (x'...')."""
        node = self.node
        assert isinstance(node, vy_ast.HexBytes)
        assert isinstance(node.value, bytes)
        return self._lower_bytelike(BytesT, node.value)

    def lower_Str(self) -> IRVariable:
        """Lower string literal ('...')."""
        node = self.node
        assert isinstance(node, vy_ast.Str)
        bytez = node.value.encode("utf-8")
        return self._lower_bytelike(StringT, bytez)

    def lower_Tuple(self) -> IRVariable:
        """Lower tuple literal: (a, b, c).

        Allocates memory for the tuple and stores each element at the correct offset.
        Returns pointer to the allocated tuple in memory.

        Reference: vyper/codegen/expr.py:parse_Tuple
        """
        node = self.node
        assert isinstance(node, vy_ast.Tuple)
        typ = node._metadata["type"]

        # Allocate memory for the tuple
        ptr = self.ctx.new_internal_variable(typ)

        # Store each element at its correct offset
        offset = 0
        for i, elem_node in enumerate(node.elements):
            elem_typ = typ.member_types[i]
            elem_val = Expr(elem_node, self.ctx).lower()

            if offset == 0:
                dst = ptr
            else:
                dst = self.builder.add(ptr, IRLiteral(offset))

            self.ctx.store_memory(elem_val, dst, elem_typ)
            offset += elem_typ.memory_bytes_required

        return ptr

    def lower_List(self) -> IRVariable:
        """Lower list literal: [a, b, c].

        Creates a DynArray in memory with the given elements.

        Memory layout:
            ptr+0:  length (32 bytes) - number of elements
            ptr+32: element 0
            ptr+32+elem_size: element 1
            ...

        Reference: vyper/codegen/expr.py:parse_List
        """
        node = self.node
        assert isinstance(node, vy_ast.List)
        typ = node._metadata["type"]  # DArrayT
        elem_typ = typ.value_type
        elem_size = elem_typ.memory_bytes_required
        num_elements = len(node.elements)

        # Allocate memory for the DynArray
        ptr = self.ctx.new_internal_variable(typ)

        # Store length word
        self.builder.mstore(IRLiteral(num_elements), ptr)

        # Store each element at its correct offset (after length word)
        data_offset = 32  # Skip length word
        for elem_node in node.elements:
            elem_val = Expr(elem_node, self.ctx).lower()

            if data_offset == 32:
                dst = self.builder.add(ptr, IRLiteral(32))
            else:
                dst = self.builder.add(ptr, IRLiteral(data_offset))

            self.ctx.store_memory(elem_val, dst, elem_typ)
            data_offset += elem_size

        return ptr

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

    def lower_BinOp(self) -> IROperand:
        """Lower binary operations with appropriate overflow checking."""
        node = self.node
        assert isinstance(node, vy_ast.BinOp)
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

    def _safe_add(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Add with overflow checking."""
        return safe_add(self.builder, x, y, typ)

    def _safe_sub(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Subtract with overflow checking."""
        return safe_sub(self.builder, x, y, typ)

    def _safe_mul(self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp) -> IROperand:
        """Multiply with overflow checking."""
        return safe_mul(self.builder, x, y, typ)

    def _safe_div(self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp) -> IROperand:
        """Decimal division with overflow checking."""
        return safe_div(self.builder, x, y, typ)

    def _safe_floordiv(self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp) -> IROperand:
        """Integer floor division with overflow checking."""
        return safe_floordiv(self.builder, x, y, typ)

    def _safe_mod(self, x: IROperand, y: IROperand, typ) -> IROperand:
        """Modulo with divisor check."""
        return safe_mod(self.builder, x, y, typ)

    def _safe_pow(self, x: IROperand, y: IROperand, typ, node: vy_ast.BinOp) -> IROperand:
        """Exponentiation with bounds checking.

        Requires at least one operand to be a literal for bounds computation.
        """
        # Get the reduced nodes to check for literals
        left_node = node.left.reduced()
        right_node = node.right.reduced()

        base_literal = left_node.value if isinstance(left_node, vy_ast.Int) else None
        exp_literal = right_node.value if isinstance(right_node, vy_ast.Int) else None

        return safe_pow(self.builder, x, y, typ, base_literal, exp_literal)

    def _clamp_basetype(self, val: IROperand, typ) -> IROperand:
        """Clamp value to type bounds."""
        return clamp_basetype(self.builder, val, typ)

    # === Unary Operations ===

    def lower_UnaryOp(self) -> IRVariable:
        """Lower unary operations."""
        node = self.node
        assert isinstance(node, vy_ast.UnaryOp)
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
        assert isinstance(node, vy_ast.Compare)
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
                # Array membership - use loop with early break
                location = node.right._expr_info.location
                return self._lower_array_membership(
                    left, right, right_typ, location, isinstance(op, vy_ast.In)
                )

        # Determine if we need signed or unsigned comparison
        # UINT256 uses unsigned comparisons; all other types use signed
        use_unsigned = left_typ == UINT256_T and right_typ == UINT256_T

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
        assert isinstance(node, vy_ast.BoolOp)
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
        node = self.node
        assert isinstance(node, vy_ast.Name)
        varname = node.id

        # Case 1: "self" keyword -> address opcode
        if varname == "self":
            return self.builder.address()

        # Get variable info from semantic analysis
        varinfo = node._expr_info.var_info
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
        node = self.node
        assert isinstance(node, vy_ast.Attribute)
        typ = node._metadata["type"]

        # Case 1: Flag constants (MyFlag.VALUE)
        if isinstance(typ, FlagT):
            value_typ = node.value._metadata.get("type")
            # Check if this is a flag type access (e.g., MyFlag.VALUE)
            if hasattr(value_typ, "_flag_members"):
                flag_id = typ._flag_members[node.attr]
                value = 2**flag_id  # 0 => 1, 1 => 2, 2 => 4, etc.
                return IRLiteral(value)

        # Case 2: Address properties
        attr = node.attr
        if attr == "balance":
            sub = Expr(node.value, self.ctx).lower()
            # Check if it's self.balance
            if isinstance(node.value, vy_ast.Name) and node.value.id == "self":
                return self.builder.selfbalance()
            return self.builder.balance(sub)

        if attr == "codesize":
            if isinstance(node.value, vy_ast.Name) and node.value.id == "self":
                return self.builder.codesize()
            sub = Expr(node.value, self.ctx).lower()
            return self.builder.extcodesize(sub)

        if attr == "is_contract":
            sub = Expr(node.value, self.ctx).lower()
            codesize = self.builder.extcodesize(sub)
            return self.builder.gt(codesize, IRLiteral(0))

        if attr == "codehash":
            sub = Expr(node.value, self.ctx).lower()
            return self.builder.extcodehash(sub)

        # Case 3: Environment variables (msg.*, block.*, tx.*, chain.*)
        if isinstance(node.value, vy_ast.Name) and node.value.id in ENVIRONMENT_VARIABLES:
            return self._lower_environment_attr()

        # Case 4: State variables (self.x)
        varinfo = node._expr_info.var_info
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

        sub_typ = node.value._metadata.get("type")
        if isinstance(sub_typ, InterfaceT) and attr == "address":
            return Expr(node.value, self.ctx).lower()

        # Case 6: Struct field access (point.x)
        if isinstance(sub_typ, StructT) and attr in sub_typ.member_types:
            return self._lower_struct_field()

        raise CompilerPanic(f"Unsupported attribute access: {node.attr}")

    def _lower_environment_attr(self) -> IROperand:
        """Lower environment variable attributes (msg.*, block.*, tx.*, chain.*)."""
        node = self.node
        assert isinstance(node, vy_ast.Attribute)
        assert isinstance(node.value, vy_ast.Name)
        key = f"{node.value.id}.{node.attr}"

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

    # === Ternary Expression ===

    def lower_IfExp(self) -> IRVariable:
        """Lower ternary expression: x if cond else y"""
        node = self.node
        assert isinstance(node, vy_ast.IfExp)

        cond = Expr(node.test, self.ctx).lower()
        cond_block = self.builder.current_block

        then_block = self.builder.create_block("ternary_then")
        else_block = self.builder.create_block("ternary_else")

        # Pre-allocate result variable
        result = self.builder.new_variable()

        # Process then branch
        self.builder.append_block(then_block)
        self.builder.set_block(then_block)
        then_val = Expr(node.body, self.ctx).lower()
        then_block_finish = self.builder.current_block
        then_block_finish.append_instruction("assign", then_val, ret=result)

        # Process else branch
        self.builder.append_block(else_block)
        self.builder.set_block(else_block)
        else_val = Expr(node.orelse, self.ctx).lower()
        else_block_finish = self.builder.current_block
        else_block_finish.append_instruction("assign", else_val, ret=result)

        # Add jnz to cond_block
        cond_block.append_instruction("jnz", cond, then_block.label, else_block.label)

        # Create exit block and add jumps
        exit_block = self.builder.create_block("ternary_exit")
        self.builder.append_block(exit_block)
        self.builder.set_block(exit_block)

        then_block_finish.append_instruction("jmp", exit_block.label)
        else_block_finish.append_instruction("jmp", exit_block.label)

        return result

    # === Subscript Operations ===

    def lower_Subscript(self) -> IROperand:
        """Lower subscript access: array[index], mapping[key], or tuple[N].

        Returns a pointer/slot that the caller can load from or store to.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base_typ = node.value._metadata["type"]

        if isinstance(base_typ, HashMapT):
            return self._lower_mapping_subscript()
        elif isinstance(base_typ, (SArrayT, DArrayT)):
            return self._lower_array_subscript()
        elif isinstance(base_typ, StructT):
            # Tuple access on struct (struct[0], struct[1], etc.)
            return self._lower_tuple_subscript()
        else:
            raise CompilerPanic(f"Unsupported subscript on {base_typ}")

    def _lower_array_subscript(self, bounds_check: bool = True) -> IROperand:
        """Lower array[index] access.

        Computes element pointer with bounds checking:
        - Static arrays: bounds check against compile-time count
        - Dynamic arrays: load length from first word, skip 32/1 for data

        Returns pointer to element (memory ptr or storage slot).
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base = Expr(node.value, self.ctx).lower()
        index = Expr(node.slice, self.ctx).lower()

        # If index is from memory, load it
        if isinstance(index, IRVariable):
            # Check if it's a memory location (not already a value)
            # For now, assume lower() already loads values
            pass

        base_typ = node.value._metadata["type"]
        elem_typ = base_typ.value_type
        index_typ = node.slice._metadata["type"]

        # Determine location and element size
        # For memory arrays: word_scale=32, sizes in bytes
        # For storage arrays: word_scale=1, sizes in slots
        is_storage = self._is_storage_access(node.value)
        if is_storage:
            data_loc = DataLocation.STORAGE
            word_scale = 1
        else:
            data_loc = DataLocation.MEMORY
            word_scale = 32

        elem_size = elem_typ.get_size_in(data_loc)

        # Bounds checking
        if bounds_check:
            length: IROperand = IRLiteral(0)
            if isinstance(base_typ, DArrayT):
                # Dynamic array: load length from first word
                if is_storage:
                    length = self.builder.sload(base)
                else:
                    length = self.builder.mload(base)
            else:
                # Static array: compile-time length
                length = IRLiteral(base_typ.count)

            # Check: not (index < 0) and not (index >= length)
            # For signed indices, check negativity; for unsigned, skip
            is_neg: IROperand
            if isinstance(index_typ, IntegerT) and index_typ.is_signed:
                is_neg = self.builder.slt(index, IRLiteral(0))
            else:
                is_neg = IRLiteral(0)

            # Always use unsigned comparison for out-of-bounds
            # ge(a, b) = not lt(a, b)
            is_oob = self.builder.iszero(self.builder.lt(index, length))
            invalid = self.builder.or_(is_neg, is_oob)
            valid = self.builder.iszero(invalid)
            self.builder.assert_(valid)

        # Compute data pointer (skip length word for dynamic arrays)
        data_ptr: IROperand
        if isinstance(base_typ, DArrayT):
            overhead = word_scale * DYNAMIC_ARRAY_OVERHEAD
            data_ptr = self.builder.add(base, IRLiteral(overhead))
        else:
            data_ptr = base

        # Compute element offset: index * elem_size
        offset = self.builder.mul(index, IRLiteral(elem_size))
        elem_ptr = self.builder.add(data_ptr, offset)

        return elem_ptr

    def _lower_mapping_subscript(self) -> IROperand:
        """Lower mapping[key] access.

        Computes storage slot via keccak256(slot || key):
        - Simple keys (int, address, bytes32): use directly
        - Complex keys (bytes, string): pre-hash with keccak256

        Returns storage slot as IROperand.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base = Expr(node.value, self.ctx).lower()
        key_typ = node.value._metadata["type"].key_type

        # Handle bytes/string keys - need to hash them first
        if isinstance(key_typ, _BytestringT):
            key = self._lower_keccak256_key(node.slice)
        else:
            key = Expr(node.slice, self.ctx).lower()

        # sha3_64(slot, key) = keccak256(concat(slot, key))
        # Both are 32 bytes, concatenated and hashed
        slot = self.builder.sha3_64(base, key)

        return slot

    def _lower_keccak256_key(self, key_node: vy_ast.VyperNode) -> IROperand:
        """Hash a bytes/string key for use as mapping key.

        For bytes32: mstore to scratch, sha3
        For bytes/string: ensure in memory, sha3 data portion
        """
        key_typ = key_node._metadata["type"]

        if key_typ == BYTES32_T:
            # bytes32: mstore to free var space and hash
            key = Expr(key_node, self.ctx).lower()
            self.builder.mstore(key, IRLiteral(MemoryPositions.FREE_VAR_SPACE))
            return self.builder.sha3(IRLiteral(MemoryPositions.FREE_VAR_SPACE), IRLiteral(32))

        # bytes/string: already in memory from lower(), hash the data portion
        key_ptr = Expr(key_node, self.ctx).lower()
        # Data starts at ptr+32 (after length word)
        data_ptr = self.builder.add(key_ptr, IRLiteral(32))
        # Length is at ptr
        length = self.builder.mload(key_ptr)
        return self.builder.sha3(data_ptr, length)

    def _lower_tuple_subscript(self) -> IROperand:
        """Lower tuple[N] or struct[N] access.

        Index must be a compile-time constant. Computes offset by summing
        sizes of preceding elements.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base = Expr(node.value, self.ctx).lower()
        base_typ = node.value._metadata["type"]

        # Get the compile-time index
        reduced_slice = node.slice.reduced()
        assert isinstance(reduced_slice, vy_ast.Int)
        index = reduced_slice.value

        # Determine location
        is_storage = self._is_storage_access(node.value)
        data_loc = DataLocation.STORAGE if is_storage else DataLocation.MEMORY

        # Compute offset by summing sizes of preceding elements
        attrs = list(base_typ.tuple_keys())
        offset = 0
        for i in range(index):
            t = base_typ.member_types[attrs[i]]
            offset += t.get_size_in(data_loc)

        if offset == 0:
            return base
        return self.builder.add(base, IRLiteral(offset))

    def _lower_struct_field(self) -> IROperand:
        """Lower struct.field access.

        Computes field pointer by summing sizes of preceding fields.
        """
        node = self.node
        assert isinstance(node, vy_ast.Attribute)
        base = Expr(node.value, self.ctx).lower()
        base_typ = node.value._metadata["type"]
        attr = node.attr

        # Determine location
        is_storage = self._is_storage_access(node.value)
        data_loc = DataLocation.STORAGE if is_storage else DataLocation.MEMORY

        # Find field index and compute offset
        attrs = list(base_typ.tuple_keys())
        field_index = attrs.index(attr)

        offset = 0
        for i in range(field_index):
            t = base_typ.member_types[attrs[i]]
            offset += t.get_size_in(data_loc)

        if offset == 0:
            return base
        return self.builder.add(base, IRLiteral(offset))

    def _is_storage_access(self, node: vy_ast.VyperNode) -> bool:
        """Check if an expression refers to storage.

        Returns True if the access is to storage/transient, False for memory.
        """
        # self.x -> storage
        if isinstance(node, vy_ast.Attribute):
            if isinstance(node.value, vy_ast.Name) and node.value.id == "self":
                varinfo = node._expr_info.var_info
                if varinfo is not None and not varinfo.is_constant and not varinfo.is_immutable:
                    return True
            # Nested: self.x.field or self.x[i]
            return self._is_storage_access(node.value)

        # Subscript on storage: self.arr[i]
        if isinstance(node, vy_ast.Subscript):
            return self._is_storage_access(node.value)

        # Local variables are in memory
        if isinstance(node, vy_ast.Name):
            return False

        return False

    def _lower_array_membership(
        self, needle: IROperand, haystack: IROperand, haystack_typ,
        location: DataLocation, is_in: bool
    ) -> IRVariable:
        """Lower array membership test: x in array or x not in array.

        Uses a loop with early break:
        - result = 0 (not found)
        - for each element:
            - if element == needle: result = 1, break
        - return result (or iszero(result) for not in)
        """
        # Determine word scale based on location
        # Storage: 1 slot per word, Memory: 32 bytes per word
        word_scale = 1 if location == DataLocation.STORAGE else 32

        # Get array properties
        length: IROperand
        if isinstance(haystack_typ, DArrayT):
            length = self.builder.load(haystack, location)
            bound = haystack_typ.count
            offset_base = word_scale * DYNAMIC_ARRAY_OVERHEAD
        elif isinstance(haystack_typ, SArrayT):
            length = IRLiteral(haystack_typ.count)
            bound = haystack_typ.count
            offset_base = 0
        else:
            raise CompilerPanic(f"Cannot check membership in type: {haystack_typ}")

        elem_size = haystack_typ.value_type.get_size_in(location)

        # Pre-allocate result variable
        result = self.builder.new_variable()

        # Create blocks
        entry_block = self.builder.create_block("in_entry")
        cond_block = self.builder.create_block("in_cond")
        body_block = self.builder.create_block("in_body")
        found_block = self.builder.create_block("in_found")
        incr_block = self.builder.create_block("in_incr")
        exit_block = self.builder.create_block("in_exit")

        # Jump to entry
        self.builder.jmp(entry_block.label)

        # Entry: initialize index and result
        self.builder.append_block(entry_block)
        self.builder.set_block(entry_block)
        index_var = self.builder.assign(IRLiteral(0))
        self.builder.assign_to(IRLiteral(0), result)  # result = 0 (not found)

        # Bound check for dynamic arrays
        if isinstance(haystack_typ, DArrayT):
            invalid = self.builder.gt(length, IRLiteral(bound))
            valid = self.builder.iszero(invalid)
            self.builder.assert_(valid)

        self.builder.jmp(cond_block.label)

        # Condition: check if index == length
        self.builder.append_block(cond_block)
        self.builder.set_block(cond_block)
        done = self.builder.eq(index_var, length)
        cond_finish = self.builder.current_block

        # Body: load element and compare
        self.builder.append_block(body_block)
        self.builder.set_block(body_block)

        # Compute element address
        index_offset = self.builder.mul(index_var, IRLiteral(elem_size))
        if offset_base > 0:
            total_offset = self.builder.add(IRLiteral(offset_base), index_offset)
        else:
            total_offset = index_offset
        elem_addr = self.builder.add(haystack, total_offset)

        # Load element and compare
        elem_val = self.builder.load(elem_addr, location)
        match = self.builder.eq(elem_val, needle)
        self.builder.jnz(match, found_block.label, incr_block.label)

        # Found block: set result = 1, jump to exit
        self.builder.append_block(found_block)
        self.builder.set_block(found_block)
        self.builder.assign_to(IRLiteral(1), result)
        self.builder.jmp(exit_block.label)

        # Increment block
        self.builder.append_block(incr_block)
        self.builder.set_block(incr_block)
        new_index = self.builder.add(index_var, IRLiteral(1))
        self.builder.assign_to(new_index, index_var)
        self.builder.jmp(cond_block.label)

        # Add conditional jump to cond block
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        self.builder.append_block(exit_block)
        self.builder.set_block(exit_block)

        # For "not in", invert the result
        if is_in:
            return result
        else:
            return self.builder.iszero(result)

    # === Function Calls ===

    def lower_Call(self) -> IROperand:
        """Lower function call.

        Handles:
        - Internal function calls (self.func())
        - Built-in functions (len, abs, etc.)
        - Struct constructors (MyStruct(...))
        - Interface constructors (MyInterface(<address>))
        - DynArray methods (.append(), .pop())
        - External calls (interface.method()) - deferred to Task 14
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        func = node.func
        func_t = func._metadata.get("type")

        # Check if this is an internal call (self.func())
        if isinstance(func, vy_ast.Attribute):
            if isinstance(func.value, vy_ast.Name) and func.value.id == "self":
                return self._lower_internal_call()

        # Built-in functions
        if isinstance(func_t, BuiltinFunctionT):
            return self._lower_builtin_call(func_t)

        # Struct constructor: MyStruct(field1=val1, field2=val2)
        if func_t is not None and is_type_t(func_t, StructT):
            return self._lower_struct_constructor()

        # Interface constructor: MyInterface(<address>)
        if func_t is not None and is_type_t(func_t, InterfaceT):
            return self._lower_interface_constructor()

        # DynArray methods: arr.append(val), arr.pop()
        if isinstance(func_t, MemberFunctionT):
            return self._lower_member_function_call(func_t)

        raise CompilerPanic(f"Unsupported call: {node.func}")

    def _lower_internal_call(self) -> IROperand:
        """Lower internal function call (self.func(...)).

        Calling convention:
        1. Allocate return buffer if needed
        2. Store memory-passed args to calloca slots
        3. Load stack-passed args to stack
        4. Emit invoke instruction
        5. For multi-return, copy stack outputs to caller memory
        """
        from vyper.venom.basicblock import IRLabel

        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func_name = node.func.attr

        # Get function type from the function attribute's metadata
        # node._metadata["type"] is the return type, we need the function type
        func_t = node.func._metadata.get("type")
        assert func_t is not None

        returns_count = self.ctx.returns_stack_count(func_t)
        pass_via_stack = self.ctx.pass_via_stack(func_t)

        # Generate function label
        # Format: "internal {function_id} {name}({arg_types})_runtime"
        suffix = "_deploy" if self.ctx.is_ctor_context else "_runtime"
        argz = ",".join([str(arg.typ) for arg in func_t.arguments])
        target_label = f"internal {func_t._function_id} {func_name}({argz}){suffix}"

        # Allocate return buffer
        return_buf = None
        if func_t.return_type is not None:
            if returns_count > 0:
                # Multi-return: allocate scratch buffer
                alloca_id = self.ctx.new_alloca_id()
                return_buf = self.builder.alloca(32 * returns_count, alloca_id)
            else:
                # Memory return: allocate buffer for full return type
                return_buf = self.ctx.new_internal_variable(func_t.return_type)

        # Prepare arguments
        invoke_args: list[IROperand] = []  # Stack args for invoke

        # First: return buffer pointer if memory return (not multi-return)
        if return_buf is not None and returns_count == 0:
            invoke_args.append(return_buf)

        # Evaluate and stage arguments
        for i, arg_node in enumerate(node.args):
            arg_t = func_t.arguments[i]
            arg_val = Expr(arg_node, self.ctx).lower()

            if pass_via_stack[arg_t.name]:
                # Stack-passed arg: load value
                if arg_t.typ._is_prim_word:
                    invoke_args.append(arg_val)
                else:
                    # Complex stack arg - load from memory
                    invoke_args.append(self.builder.mload(arg_val))
            else:
                # Memory-passed arg: already in memory, callee will access via palloca
                # Nothing to add to invoke_args for memory args
                pass

        # Emit invoke instruction
        if returns_count > 0:
            outs = self.builder.invoke(IRLabel(target_label), invoke_args, returns=returns_count)
            # Copy stack returns to buffer
            assert return_buf is not None
            for i, outv in enumerate(outs):
                if i == 0:
                    dst = return_buf
                else:
                    dst = self.builder.add(return_buf, IRLiteral(i * 32))
                self.builder.mstore(outv, dst)
        else:
            self.builder.invoke(IRLabel(target_label), invoke_args, returns=0)

        # Return the return buffer (or load from it for single word)
        if return_buf is not None:
            if func_t.return_type._is_prim_word:
                return self.builder.mload(return_buf)
            return return_buf

        return IRLiteral(0)  # void return

    # === Builtin Function Calls ===

    def _lower_builtin_call(self, func_t: BuiltinFunctionT) -> IROperand:
        """Dispatch builtin function calls to handlers in builtins/ submodule."""
        from vyper.codegen_venom.builtins import lower_builtin

        return lower_builtin(func_t._id, self.node, self.ctx)

    # === Constructor and Member Function Calls ===

    def _lower_struct_constructor(self) -> IROperand:
        """Lower struct constructor call: MyStruct(field1=val1, ...).

        Allocates memory for struct and stores field values in field order.

        Reference: vyper/codegen/expr.py:handle_struct_literal
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        func_t = node.func._metadata.get("type")
        assert func_t is not None
        struct_t = func_t.typedef  # Get the actual StructT

        # Allocate memory for the struct
        ptr = self.ctx.new_internal_variable(struct_t)

        # Build map of field name -> value node from keywords
        member_vals = {}
        for kwarg in node.keywords:
            member_vals[kwarg.arg] = kwarg.value

        # Store each field at its correct offset (in struct field order)
        offset = 0
        for field_name in struct_t.tuple_keys():
            field_typ = struct_t.member_types[field_name]
            field_val = Expr(member_vals[field_name], self.ctx).lower()

            if offset == 0:
                dst = ptr
            else:
                dst = self.builder.add(ptr, IRLiteral(offset))

            self.ctx.store_memory(field_val, dst, field_typ)
            offset += field_typ.memory_bytes_required

        return ptr

    def _lower_interface_constructor(self) -> IROperand:
        """Lower interface constructor call: MyInterface(<address>).

        Returns the address value - interface types are just addresses at runtime.
        The type annotation is used by the type system but doesn't affect codegen.
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        # Interface constructor takes exactly one argument: the address
        assert len(node.args) == 1
        return Expr(node.args[0], self.ctx).lower()

    def _lower_member_function_call(self, func_t: MemberFunctionT) -> IROperand:
        """Lower DynArray member function calls: .append(), .pop().

        - append(val): increment length, store value at end
        - pop(): decrement length, return popped value
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func = node.func
        attr = func.attr

        if attr == "append":
            return self._lower_dynarray_append()
        elif attr == "pop":
            return self._lower_dynarray_pop()
        else:
            raise CompilerPanic(f"Unknown member function: {attr}")

    def _lower_dynarray_append(self) -> IROperand:
        """Lower DynArray.append(val).

        1. Load current length
        2. Assert length < capacity (bounds check)
        3. Compute element pointer: data_ptr + length * elem_size
        4. Store element
        5. Increment and store new length

        Reference: vyper/codegen/core.py:append_dyn_array
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func = node.func
        darray_node = func.value  # The DynArray being appended to
        darray_typ = darray_node._metadata["type"]
        elem_typ = darray_typ.value_type

        # Get the array pointer
        darray_ptr = Expr(darray_node, self.ctx).lower()

        # Get the element value
        assert len(node.args) == 1
        elem_val = Expr(node.args[0], self.ctx).lower()

        # Determine if storage or memory
        is_storage = self._is_storage_access(darray_node)

        if is_storage:
            data_loc = DataLocation.STORAGE
            word_scale = 1  # Storage is word-addressed
        else:
            data_loc = DataLocation.MEMORY
            word_scale = 32  # Memory is byte-addressed

        elem_size = elem_typ.get_size_in(data_loc)
        capacity = darray_typ.count  # Maximum length

        # 1. Load current length
        if is_storage:
            length = self.ctx.get_storage_dyn_array_length(darray_ptr)
        else:
            length = self.ctx.get_memory_dyn_array_length(darray_ptr)

        # 2. Assert length < capacity
        valid = self.builder.lt(length, IRLiteral(capacity))
        self.builder.assert_(valid)

        # 3. Compute element pointer: data_ptr + length * elem_size
        overhead = word_scale * DYNAMIC_ARRAY_OVERHEAD
        data_ptr = self.builder.add(darray_ptr, IRLiteral(overhead))
        offset = self.builder.mul(length, IRLiteral(elem_size))
        elem_ptr = self.builder.add(data_ptr, offset)

        # 4. Store element
        if is_storage:
            self.ctx.store_storage(elem_val, elem_ptr, elem_typ)
        else:
            self.ctx.store_memory(elem_val, elem_ptr, elem_typ)

        # 5. Increment and store new length
        new_length = self.builder.add(length, IRLiteral(1))
        if is_storage:
            self.ctx.set_storage_dyn_array_length(darray_ptr, new_length)
        else:
            self.ctx.set_memory_dyn_array_length(darray_ptr, new_length)

        # append() returns nothing
        return IRLiteral(0)

    def _lower_dynarray_pop(self) -> IROperand:
        """Lower DynArray.pop().

        1. Load current length
        2. Assert length > 0 (can't pop empty)
        3. Compute new_length = length - 1
        4. Store new length
        5. Return pointer to element at new_length index

        Reference: vyper/codegen/core.py:pop_dyn_array
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func = node.func
        darray_node = func.value  # The DynArray being popped from
        darray_typ = darray_node._metadata["type"]
        elem_typ = darray_typ.value_type

        # Get the array pointer
        darray_ptr = Expr(darray_node, self.ctx).lower()

        # Determine if storage or memory
        is_storage = self._is_storage_access(darray_node)

        if is_storage:
            data_loc = DataLocation.STORAGE
            word_scale = 1  # Storage is word-addressed
        else:
            data_loc = DataLocation.MEMORY
            word_scale = 32  # Memory is byte-addressed

        elem_size = elem_typ.get_size_in(data_loc)

        # 1. Load current length
        if is_storage:
            length = self.ctx.get_storage_dyn_array_length(darray_ptr)
        else:
            length = self.ctx.get_memory_dyn_array_length(darray_ptr)

        # 2. Assert length > 0 (can't pop empty array)
        valid = self.builder.iszero(self.builder.iszero(length))
        self.builder.assert_(valid)

        # 3. Compute new_length = length - 1
        new_length = self.builder.sub(length, IRLiteral(1))

        # 4. Store new length
        if is_storage:
            self.ctx.set_storage_dyn_array_length(darray_ptr, new_length)
        else:
            self.ctx.set_memory_dyn_array_length(darray_ptr, new_length)

        # 5. Return element at new_length index (the popped element)
        # We return the value, not the pointer
        overhead = word_scale * DYNAMIC_ARRAY_OVERHEAD
        data_ptr = self.builder.add(darray_ptr, IRLiteral(overhead))
        offset = self.builder.mul(new_length, IRLiteral(elem_size))
        elem_ptr = self.builder.add(data_ptr, offset)

        # Load and return the value
        if is_storage:
            return self.ctx.load_storage(elem_ptr, elem_typ)
        else:
            return self.ctx.load_memory(elem_ptr, elem_typ)

    # === External Calls ===

    def lower_ExtCall(self) -> IROperand:
        """Lower extcall statement (mutable external call).

        extcall interface.method(args, value=..., gas=...)
        """
        return self._lower_external_call()

    def lower_StaticCall(self) -> IROperand:
        """Lower staticcall expression (view/pure external call).

        result: T = staticcall interface.method(args, gas=...)
        """
        return self._lower_external_call()

    def _parse_external_call_kwargs(self, call_node) -> _CallKwargs:
        """Parse keyword arguments for external calls.

        Handles: value, gas, skip_contract_check, default_return_value

        Args:
            call_node: The Call AST node (from ExtCall.value or StaticCall.value)
        """
        # Default values
        value: IROperand = IRLiteral(0)
        gas: IROperand = self.builder.gas()
        skip_contract_check = False
        default_return_value = None

        for kw in call_node.keywords:
            kw_val = Expr(kw.value, self.ctx).lower()
            if kw.arg == "value":
                value = kw_val
            elif kw.arg == "gas":
                gas = kw_val
            elif kw.arg == "skip_contract_check":
                # Must be a literal True/False
                if not isinstance(kw_val, IRLiteral):
                    raise CompilerPanic(f"Expected IRLiteral for keyword, got {type(kw_val)}")
                skip_contract_check = bool(kw_val.value)
            elif kw.arg == "default_return_value":
                default_return_value = kw_val
            else:
                raise CompilerPanic(f"Unexpected keyword argument: {kw.arg}")

        return _CallKwargs(
            value=value,
            gas=gas,
            skip_contract_check=skip_contract_check,
            default_return_value=default_return_value,
        )

    def _lower_external_call(self) -> IROperand:
        """Lower external call (extcall/staticcall).

        Steps:
        1. Evaluate contract address
        2. Parse kwargs (value, gas, skip_contract_check, default_return_value)
        3. Pack arguments with method selector
        4. Check extcodesize if needed
        5. Dispatch CALL or STATICCALL
        6. Check success and propagate revert on failure
        7. Unpack return value if present
        """
        from vyper.codegen_venom.abi import abi_decode_to_buf, abi_encode_to_buf

        node = self.node
        b = self.builder

        # ExtCall and StaticCall nodes wrap a Call in their .value attribute
        assert isinstance(node, (vy_ast.ExtCall, vy_ast.StaticCall))
        call_node = node.value

        # Get function type from the call expression
        assert isinstance(call_node.func, vy_ast.Attribute)
        fn_type: ContractFunctionT = call_node.func._metadata["type"]

        # Evaluate contract address (the interface value)
        contract_address = Expr(call_node.func.value, self.ctx).lower()

        # Evaluate arguments
        args = [Expr(arg, self.ctx).lower() for arg in call_node.args]

        # Parse kwargs
        call_kwargs = self._parse_external_call_kwargs(call_node)

        # Calculate buffer size needed
        args_tuple_t = TupleT(tuple(fn_type.arguments[i].typ for i in range(len(args))))
        args_abi_t = args_tuple_t.abi_type
        args_abi_size = args_abi_t.size_bound()

        if fn_type.return_type is not None:
            return_abi_t = calculate_type_for_external_return(fn_type.return_type).abi_type
            return_abi_size = return_abi_t.size_bound()
        else:
            return_abi_size = 0

        # Buffer size: max(args, return) + 32 for method ID padding
        buf_size = max(args_abi_size, return_abi_size) + 32

        # Allocate buffer
        buf_t = get_type_for_exact_size(buf_size)
        buf = self.ctx.new_internal_variable(buf_t)

        # === Pack Arguments ===
        # Store method ID at buf+28 (left-padded in 32-byte word)
        # Method ID = first 4 bytes of keccak256(signature)
        abi_signature = fn_type.name + args_tuple_t.abi_type.selector_name()
        method_id = util.method_id_int(abi_signature)
        b.mstore(IRLiteral(method_id), buf)

        # ABI-encode arguments starting at buf+32
        if len(args) > 0:
            # Create temp buffer for args in memory
            args_buf = self.ctx.new_internal_variable(args_tuple_t)

            # Store each arg at its position in args_buf
            offset = 0
            for i, arg_val in enumerate(args):
                arg_typ = fn_type.arguments[i].typ
                if offset == 0:
                    dst = args_buf
                else:
                    dst = b.add(args_buf, IRLiteral(offset))
                self.ctx.store_memory(arg_val, dst, arg_typ)
                offset += arg_typ.memory_bytes_required

            # ABI-encode from args_buf to buf+32
            encode_dst = b.add(buf, IRLiteral(32))
            abi_encode_to_buf(self.ctx, encode_dst, args_buf, args_tuple_t)

        # Call starts at buf+28, length = 4 + args_abi_size
        args_ofst = b.add(buf, IRLiteral(28))
        args_len = IRLiteral(4 + args_abi_size)

        # === Contract Existence Check ===
        # If function returns nothing and skip_contract_check is False,
        # check extcodesize before call (can't rely on returndatasize check)
        if fn_type.return_type is None and not call_kwargs.skip_contract_check:
            codesize = b.extcodesize(contract_address)
            b.assert_(codesize)

        # === Dispatch CALL or STATICCALL ===
        use_staticcall = fn_type.mutability in (StateMutability.VIEW, StateMutability.PURE)

        # Return buffer location and size
        ret_ofst = buf
        ret_len = IRLiteral(return_abi_size) if return_abi_size > 0 else IRLiteral(0)

        if use_staticcall:
            success = b.staticcall(
                call_kwargs.gas, contract_address, args_ofst, args_len, ret_ofst, ret_len
            )
        else:
            success = b.call(
                call_kwargs.gas,
                contract_address,
                call_kwargs.value,
                args_ofst,
                args_len,
                ret_ofst,
                ret_len,
            )

        # === Revert Propagation ===
        # If call failed, propagate the revert data
        fail_bb = b.create_block("extcall_fail")
        cont_bb = b.create_block("extcall_cont")

        b.jnz(success, cont_bb.label, fail_bb.label)

        # Fail block: copy returndata and revert
        b.append_block(fail_bb)
        b.set_block(fail_bb)
        rds = b.returndatasize()
        b.returndatacopy(IRLiteral(0), IRLiteral(0), rds)
        b.revert(IRLiteral(0), rds)

        # Continue block
        b.append_block(cont_bb)
        b.set_block(cont_bb)

        # === Unpack Return Value ===
        if fn_type.return_type is None:
            return IRLiteral(0)

        return_t = fn_type.return_type
        wrapped_return_t = calculate_type_for_external_return(return_t)
        min_return_size = wrapped_return_t.abi_type.static_size()

        # Allocate result buffer
        result_buf = self.ctx.new_internal_variable(wrapped_return_t)

        # Handle default_return_value
        if call_kwargs.default_return_value is not None:
            # If returndatasize == 0, use default value
            rds = b.returndatasize()
            is_zero = b.iszero(rds)

            default_bb = b.create_block("extcall_default")
            decode_bb = b.create_block("extcall_decode")
            exit_bb = b.create_block("extcall_exit")

            b.jnz(is_zero, default_bb.label, decode_bb.label)

            # Default block: use default_return_value
            b.append_block(default_bb)
            b.set_block(default_bb)

            # Store default value - needs wrapping if single value
            if needs_external_call_wrap(return_t):
                # Wrap single value in tuple
                self.ctx.store_memory(call_kwargs.default_return_value, result_buf, return_t)
            else:
                self.ctx.store_memory(call_kwargs.default_return_value, result_buf, return_t)

            # Check extcodesize if not skipped (contract might have selfdestructed)
            if not call_kwargs.skip_contract_check:
                codesize = b.extcodesize(contract_address)
                b.assert_(codesize)

            b.jmp(exit_bb.label)

            # Decode block: normal ABI decode
            b.append_block(decode_bb)
            b.set_block(decode_bb)

            # Check returndatasize >= min_return_size
            rds = b.returndatasize()
            ok = b.iszero(b.lt(rds, IRLiteral(min_return_size)))
            b.assert_(ok)

            # Copy returndata to buffer and decode
            b.returndatacopy(buf, IRLiteral(0), rds)

            # Compute hi bound for decode (prevents overread)
            hi = b.add(buf, rds)
            abi_decode_to_buf(self.ctx, result_buf, buf, wrapped_return_t, hi=hi)

            b.jmp(exit_bb.label)

            # Exit block
            b.append_block(exit_bb)
            b.set_block(exit_bb)

        else:
            # No default_return_value - simple decode path
            # Check returndatasize >= min_return_size
            rds = b.returndatasize()
            ok = b.iszero(b.lt(rds, IRLiteral(min_return_size)))
            b.assert_(ok)

            # Copy returndata to buffer and decode
            b.returndatacopy(buf, IRLiteral(0), rds)

            # Compute hi bound for decode (prevents overread)
            hi = b.add(buf, rds)
            abi_decode_to_buf(self.ctx, result_buf, buf, wrapped_return_t, hi=hi)

        # Unwrap if single return value
        if needs_external_call_wrap(return_t):
            # Return the first (only) element of the wrapper tuple
            if return_t._is_prim_word:
                return b.mload(result_buf)
            else:
                return result_buf
        else:
            # Multi-return tuple
            return result_buf
