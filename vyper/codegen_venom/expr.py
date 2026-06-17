"""
Lower Vyper AST expressions to Venom IR.

This module handles the first stage of expression codegen: converting
Vyper AST literal and expression nodes into Venom IR operands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import vyper.utils as util
from vyper import ast as vy_ast
from vyper.builtins._signatures import BuiltinFunctionT
from vyper.codegen.core import (
    DYNAMIC_ARRAY_OVERHEAD,
    calculate_type_for_external_return,
    needs_external_call_wrap,
)
from vyper.codegen_venom.arithmetic import apply_binop
from vyper.exceptions import (
    CodegenPanic,
    CompilerPanic,
    StateAccessViolation,
    TypeMismatch,
    UnimplementedException,
    tag_exceptions,
)
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
    VyperType,
    is_type_t,
)
from vyper.semantics.types.base import VOID_TYPE
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT, StateMutability
from vyper.semantics.types.infinity import is_bounded_length, type_contains_unbounded_sequence
from vyper.semantics.types.shortcuts import BYTES32_T, UINT256_T
from vyper.semantics.types.subscriptable import DArrayT, HashMapT, SArrayT
from vyper.semantics.types.user import FlagT, StructT
from vyper.utils import DECIMAL_DIVISOR, keccak256
from vyper.venom.basicblock import IRLabel, IRLiteral, IROperand, IRVariable

from .abi import (
    abi_decode_to_buf,
    abi_encode_to_buf,
    abi_encode_values_to_buf,
    decode_unbounded_dynarray_to_scratch,
    runtime_abi_size_for_encode,
)
from .buffer import Buffer, Ptr
from .calling_convention import pass_via_stack, returns_dynamic_count, returns_stack_count
from .context import VenomCodegenContext
from .value import VyperValue


@dataclass
class _CallKwargs:
    """Keyword arguments for external calls."""

    value: IROperand  # ETH value to send (CALL only)
    gas: IROperand  # Gas limit for the call
    skip_contract_check: bool  # Skip extcodesize check
    default_return_value: Optional[VyperValue]  # Default if returndatasize==0


# Environment variable prefixes for attribute access
ENVIRONMENT_VARIABLES = {"block", "msg", "tx", "chain"}


class Expr:
    """Lower Vyper expressions to Venom IR.

    NOTE: The constructor automatically calls `node.reduced()` to handle constant
    variables (e.g., `FOO: constant(uint256) = 42`). When working with AST nodes
    directly in builtins without going through Expr, always use `node.reduced()`
    or check `node.has_folded_value` before isinstance checks on node type.
    """

    def __init__(self, node: vy_ast.VyperNode, ctx: VenomCodegenContext, as_ptr: bool = False):
        self.node = node.reduced()
        self.ctx = ctx
        self.builder = ctx.builder
        self.as_ptr = as_ptr  # True = return pointer, False = return value (load if needed)

    def lower(self) -> VyperValue:
        """Dispatch to type-specific lowering method.

        Returns VyperValue which may be a location (pointer/slot) or a value.
        Use lower_value() when you need the loaded value.
        """
        fn_name = f"lower_{type(self.node).__name__}"
        with tag_exceptions(self.node, fallback_exception_type=CodegenPanic, note=fn_name):
            method = getattr(self, fn_name, None)
            if method is None:  # pragma: nocover
                raise CompilerPanic(f"Unsupported expr: {type(self.node)}")
            return method()

    def lower_value(self) -> IROperand:
        """Lower and unwrap to get the value.

        Convenience method for the common case where you need the loaded value.
        """
        return self.ctx.unwrap(self.lower())

    # === Literal Lowering ===

    def lower_Int(self) -> VyperValue:
        """Lower integer literal."""
        node = self.node
        assert isinstance(node, vy_ast.Int)
        typ = node._metadata["type"]
        return VyperValue.from_stack_op(IRLiteral(node.value), typ)

    def lower_Decimal(self) -> VyperValue:
        """Lower decimal literal.

        Decimals are stored as fixed-point integers scaled by DECIMAL_DIVISOR (10^10).
        """
        node = self.node
        assert isinstance(node, vy_ast.Decimal)
        typ = node._metadata["type"]
        val = node.value * DECIMAL_DIVISOR
        return VyperValue.from_stack_op(IRLiteral(int(val)), typ)

    def lower_Hex(self) -> VyperValue:
        """Lower hex literal (address or bytesN).

        For addresses: direct int conversion.
        For bytesN: left-padded (shifted left) to align in 32-byte word.
        """
        node = self.node
        assert isinstance(node, vy_ast.Hex)
        hexstr = node.value
        t = node._metadata["type"]

        if t == AddressT():
            return VyperValue.from_stack_op(IRLiteral(int(hexstr, 16)), t)

        elif isinstance(t, BytesM_T):
            n_bytes = (len(hexstr) - 2) // 2
            # Left-pad: shift value to occupy high bytes of 32-byte word
            val = int(hexstr, 16) << 8 * (32 - n_bytes)
            return VyperValue.from_stack_op(IRLiteral(val), t)

        raise CompilerPanic(f"Unsupported Hex literal type: {t}")  # pragma: nocover

    def lower_NameConstant(self) -> VyperValue:
        """Lower True/False constants."""
        node = self.node
        assert isinstance(node, vy_ast.NameConstant)
        assert isinstance(node.value, bool)
        typ = node._metadata["type"]
        return VyperValue.from_stack_op(IRLiteral(int(node.value)), typ)

    # === Bytelike Literals ===

    def lower_Bytes(self) -> VyperValue:
        """Lower bytes literal (b'...')."""
        node = self.node
        assert isinstance(node, vy_ast.Bytes)
        return self._lower_bytelike(BytesT, node.value)

    def lower_HexBytes(self) -> VyperValue:
        """Lower hex bytes literal (x'...')."""
        node = self.node
        assert isinstance(node, vy_ast.HexBytes)
        assert isinstance(node.value, bytes)
        return self._lower_bytelike(BytesT, node.value)

    def lower_Str(self) -> VyperValue:
        """Lower string literal ('...')."""
        node = self.node
        assert isinstance(node, vy_ast.Str)
        bytez = node.value.encode("utf-8")
        return self._lower_bytelike(StringT, bytez)

    def lower_Tuple(self) -> VyperValue:
        """Lower tuple literal: (a, b, c).

        Allocates memory for the tuple and stores each element at the correct offset.
        Returns pointer to the allocated tuple in memory.

        Reference: vyper/codegen/expr.py:parse_Tuple
        """
        node = self.node
        assert isinstance(node, vy_ast.Tuple)
        typ = node._metadata["type"]

        if self.ctx.is_dynamic_tuple_frame_type(typ):
            member_values: list[IROperand] = []
            for i, elem_node in enumerate(node.elements):
                elem_typ = typ.member_types[i]
                elem_vv = Expr(elem_node, self.ctx).lower()
                if elem_typ._is_prim_word:
                    member_values.append(self.ctx.unwrap(elem_vv))
                else:
                    if self.ctx.is_unbounded_sequence_type(elem_typ):
                        elem_vv = self.ctx.copy_sequence_to_scratch(
                            elem_vv, elem_typ, annotation="tuple"
                        )
                    elif type_contains_unbounded_sequence(elem_typ):
                        raise CodegenPanic("nested INF tuple literals are not implemented")
                    else:
                        elem_vv = self.ctx.materialize_value(elem_vv, elem_typ, annotation="tuple")
                    member_ptr = self.ctx.unwrap(elem_vv)
                    member_values.append(member_ptr)

            frame = self.ctx.allocate_scratch(IRLiteral(self.ctx.dynamic_tuple_frame_size(typ)))
            for i, value in enumerate(member_values):
                cell = self.builder.add(frame, IRLiteral(i * 32))
                self.builder.mstore(cell, value)

            return self.ctx.dynamic_tuple_frame_value(frame, typ, annotation="tuple")

        # Allocate memory for the tuple
        val = self.ctx.new_temporary_value(typ)
        assert isinstance(val.operand, IRVariable)

        # Store each element at its correct offset
        offset = 0
        for i, elem_node in enumerate(node.elements):
            elem_typ = typ.member_types[i]
            elem_vv = Expr(elem_node, self.ctx).lower()

            dst = self.builder.add(val.operand, IRLiteral(offset))

            self.ctx.store_vyper_value(elem_vv, dst, elem_typ)
            offset += elem_typ.memory_bytes_required

        return val

    def lower_List(self) -> VyperValue:
        """Lower list literal: [a, b, c].

        Creates an array in memory with the given elements.
        Layout depends on the annotated type:
        - DArrayT: length word at offset 0, elements at offset 32+
        - SArrayT: no length word, elements at offset 0+

        Reference: vyper/codegen/expr.py:parse_List
        """
        node = self.node
        assert isinstance(node, vy_ast.List)
        typ = node._metadata["type"]
        elem_typ = typ.value_type
        elem_size = elem_typ.memory_bytes_required
        num_elements = len(node.elements)

        # Allocate memory for the array
        if isinstance(typ, DArrayT) and self.ctx.is_unbounded_dynarray_type(typ):
            size = IRLiteral(32 + num_elements * elem_size)
            ptr = self.ctx.allocate_scratch(size)
            val = self.ctx.dynamic_memory_value(ptr, typ, annotation="list")
        else:
            val = self.ctx.new_temporary_value(typ)
        assert isinstance(val.operand, IRVariable)

        # DArrayT has a length word at offset 0
        if isinstance(typ, DArrayT):
            self.ctx.ptr_store(val.ptr(), IRLiteral(num_elements))
            data_offset = 32  # Elements start after length word
        else:
            # SArrayT has no length word
            data_offset = 0

        # Store each element
        for elem_node in node.elements:
            elem_vv = Expr(elem_node, self.ctx).lower()

            dst = self.builder.add(val.operand, IRLiteral(data_offset))

            self.ctx.store_vyper_value(elem_vv, dst, elem_typ)
            data_offset += elem_size

        return val

    def _lower_bytelike(self, typeclass: type, bytez: bytes):
        """Allocate memory and store bytes/string literal.

        Memory layout:
            ptr+0:  length (32 bytes)
            ptr+32: data[0:32] (right-padded with zeros)
            ptr+64: data[32:64] (if needed)
            ...

        Returns VyperValue with allocated memory.
        """
        bytez_length = len(bytez)
        btype = typeclass(bytez_length)

        # Allocate memory for length word + data
        val = self.ctx.new_temporary_value(btype)

        # Store length at ptr
        self.ctx.ptr_store(val.ptr(), IRLiteral(bytez_length))

        # Store data in 32-byte chunks, right-padded with zeros
        for i in range(0, bytez_length, 32):
            chunk = (bytez + b"\x00" * 31)[i : i + 32]
            word = int.from_bytes(chunk, "big")
            offset = self.builder.add(val.operand, IRLiteral(32 + i))
            self.builder.mstore(offset, IRLiteral(word))

        return val

    # === Binary Operations ===

    def lower_BinOp(self) -> VyperValue:
        """Lower binary operations with appropriate overflow checking."""
        node = self.node
        assert isinstance(node, vy_ast.BinOp)
        left = Expr(node.left, self.ctx).lower_value()
        right = Expr(node.right, self.ctx).lower_value()
        op = node.op
        typ = node.left._metadata["type"]
        result_typ = node._metadata["type"]

        # Defensive: shifts only valid for 256-bit types
        if isinstance(op, (vy_ast.LShift, vy_ast.RShift)):
            is_valid = (isinstance(typ, IntegerT) and typ.bits == 256) or (
                isinstance(typ, BytesM_T) and typ.m == 32
            )
            if not is_valid:  # pragma: nocover
                raise CompilerPanic("Shift operations require 256-bit types")

        # Extract pow literals for bounds checking
        base_literal = None
        exp_literal = None
        if isinstance(op, vy_ast.Pow):
            left_reduced = node.left.reduced()
            right_reduced = node.right.reduced()
            base_literal = left_reduced.value if isinstance(left_reduced, vy_ast.Int) else None
            exp_literal = right_reduced.value if isinstance(right_reduced, vy_ast.Int) else None

        result = apply_binop(
            self.builder, op, left, right, typ, base_literal=base_literal, exp_literal=exp_literal
        )
        return VyperValue.from_stack_op(result, result_typ)

    # === Unary Operations ===

    def lower_UnaryOp(self) -> VyperValue:
        """Lower unary operations."""
        node = self.node
        assert isinstance(node, vy_ast.UnaryOp)
        operand = Expr(node.operand, self.ctx).lower_value()
        typ = node.operand._metadata["type"]
        result_typ = node._metadata["type"]
        op = node.op

        if isinstance(op, vy_ast.Not):
            # Boolean NOT
            if not isinstance(typ, BoolT):  # pragma: nocover
                raise CompilerPanic("Not operator only valid for bool")
            return VyperValue.from_stack_op(self.builder.iszero(operand), result_typ)

        if isinstance(op, vy_ast.Invert):
            # Bitwise NOT (~x)
            if isinstance(typ, FlagT):
                # For flags: xor with mask of all valid flag bits
                n_members = len(typ._flag_members)
                mask = (1 << n_members) - 1
                return VyperValue.from_stack_op(
                    self.builder.xor(operand, IRLiteral(mask)), result_typ
                )
            elif isinstance(typ, IntegerT) and typ.bits == 256 and not typ.is_signed:
                # For uint256: full bitwise not
                return VyperValue.from_stack_op(self.builder.not_(operand), result_typ)
            elif isinstance(typ, BytesM_T) and typ.m == 32:
                # For bytes32: full bitwise not
                return VyperValue.from_stack_op(self.builder.not_(operand), result_typ)
            else:
                raise UnimplementedException(f"Bitwise not is not supported for type {typ}")

        if isinstance(op, vy_ast.USub):
            # Unary minus (-x) - only for signed integers
            if not isinstance(typ, (IntegerT, DecimalT)):  # pragma: nocover
                raise CompilerPanic("USub only valid for numeric types")
            if not typ.is_signed:  # pragma: nocover
                raise CompilerPanic("USub only valid for signed types")

            # Check operand > min_int to prevent negating MIN_INT
            min_int_val, _ = typ.int_bounds
            ok = self.builder.sgt(operand, IRLiteral(min_int_val))
            self.builder.assert_(ok)

            return VyperValue.from_stack_op(self.builder.sub(IRLiteral(0), operand), result_typ)

        raise CompilerPanic(f"Unsupported UnaryOp: {type(op)}")  # pragma: nocover

    # === Comparison Operations ===

    def lower_Compare(self) -> VyperValue:
        """Lower comparison operations.

        Comparisons: <, <=, >, >=, ==, !=
        Membership: in, not in (for flags)

        Note: Array membership (in/not in for arrays) is handled separately
        and requires loops, which will be implemented with control flow.
        """
        node = self.node
        assert isinstance(node, vy_ast.Compare)
        op = node.op
        left_typ = node.left._metadata["type"]
        right_typ = node.right._metadata["type"]
        result_typ = BoolT()  # Comparisons always return bool

        # Bytestring comparison: compare keccak256 hashes
        # Must handle before lower_value() since we need VyperValue with location
        if isinstance(left_typ, _BytestringT) and isinstance(right_typ, _BytestringT):
            if not isinstance(op, (vy_ast.Eq, vy_ast.NotEq)):  # pragma: nocover
                raise CompilerPanic(f"Unsupported comparison for bytestrings: {type(op)}")

            # Get hash for each side - use compile-time hash for constants
            left_hash = self._get_bytestring_hash(node.left)
            right_hash = self._get_bytestring_hash(node.right)

            if isinstance(op, vy_ast.Eq):
                return VyperValue.from_stack_op(self.builder.eq(left_hash, right_hash), result_typ)
            else:  # NotEq
                return VyperValue.from_stack_op(
                    self.builder.iszero(self.builder.eq(left_hash, right_hash)), result_typ
                )

        # Handle membership tests (In/NotIn) - need special handling for arrays
        if isinstance(op, (vy_ast.In, vy_ast.NotIn)):
            left = Expr(node.left, self.ctx).lower_value()

            if isinstance(right_typ, FlagT):
                # x in flags: check if (x & flags) != 0
                # x not in flags: check if (x & flags) == 0
                right = Expr(node.right, self.ctx).lower_value()
                intersection = self.builder.and_(left, right)
                if isinstance(op, vy_ast.In):
                    # iszero(iszero(x)) = 1 if x != 0
                    return VyperValue.from_stack_op(
                        self.builder.iszero(self.builder.iszero(intersection)), result_typ
                    )
                else:  # NotIn
                    return VyperValue.from_stack_op(self.builder.iszero(intersection), result_typ)
            else:
                # Array membership
                # For list literals, unroll to equality chain (more efficient)
                if isinstance(node.right, vy_ast.List):
                    return VyperValue.from_stack_op(
                        self._lower_list_literal_membership(
                            left, node.right, isinstance(op, vy_ast.In)
                        ),
                        result_typ,
                    )
                # For storage/memory arrays, use loop with early break
                # Don't unwrap - iterate directly over storage/memory location
                right_val = Expr(node.right, self.ctx).lower()
                return VyperValue.from_stack_op(
                    self._lower_array_membership(
                        left, right_val, right_typ, isinstance(op, vy_ast.In)
                    ),
                    result_typ,
                )

        # Non-bytestring: get values directly
        left = Expr(node.left, self.ctx).lower_value()
        right = Expr(node.right, self.ctx).lower_value()

        # Determine if we need signed or unsigned comparison
        # UINT256 uses unsigned comparisons; all other types use signed
        use_unsigned = left_typ == UINT256_T and right_typ == UINT256_T

        # Dispatch to appropriate comparison
        if isinstance(op, vy_ast.Lt):
            if use_unsigned:
                return VyperValue.from_stack_op(self.builder.lt(left, right), result_typ)
            return VyperValue.from_stack_op(self.builder.slt(left, right), result_typ)

        if isinstance(op, vy_ast.Gt):
            if use_unsigned:
                return VyperValue.from_stack_op(self.builder.gt(left, right), result_typ)
            return VyperValue.from_stack_op(self.builder.sgt(left, right), result_typ)

        if isinstance(op, vy_ast.Eq):
            return VyperValue.from_stack_op(self.builder.eq(left, right), result_typ)

        if isinstance(op, vy_ast.NotEq):
            # ne = iszero(eq)
            return VyperValue.from_stack_op(
                self.builder.iszero(self.builder.eq(left, right)), result_typ
            )

        if isinstance(op, vy_ast.LtE):
            # le = iszero(gt)
            if use_unsigned:
                return VyperValue.from_stack_op(
                    self.builder.iszero(self.builder.gt(left, right)), result_typ
                )
            return VyperValue.from_stack_op(
                self.builder.iszero(self.builder.sgt(left, right)), result_typ
            )

        if isinstance(op, vy_ast.GtE):
            # ge = iszero(lt)
            if use_unsigned:
                return VyperValue.from_stack_op(
                    self.builder.iszero(self.builder.lt(left, right)), result_typ
                )
            return VyperValue.from_stack_op(
                self.builder.iszero(self.builder.slt(left, right)), result_typ
            )

        raise CompilerPanic(f"Unsupported comparison op: {type(op)}")  # pragma: nocover

    # === Boolean Operations ===

    def lower_BoolOp(self) -> VyperValue:
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
                cond = Expr(val, self.ctx).lower_value()
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
            last_val = Expr(values[-1], self.ctx).lower_value()
            self.builder.assign_to(last_val, result)
            self.builder.jmp(exit_bb.label)

        elif isinstance(op, vy_ast.Or):
            # a or b or c:
            # evaluate a, if true -> result=1, jump to exit
            # evaluate b, if true -> result=1, jump to exit
            # ...
            # evaluate last, result = last value, jump to exit
            for val in values[:-1]:
                cond = Expr(val, self.ctx).lower_value()
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
            last_val = Expr(values[-1], self.ctx).lower_value()
            self.builder.assign_to(last_val, result)
            self.builder.jmp(exit_bb.label)

        else:  # pragma: nocover
            raise CompilerPanic(f"Unsupported BoolOp: {type(op)}")

        # Continue from exit block
        self.builder.append_block(exit_bb)
        self.builder.set_block(exit_bb)

        return VyperValue.from_stack_op(result, BoolT())

    # === Variable and Name Operations ===

    def lower_Name(self) -> VyperValue:
        """Lower name reference.

        Handles:
        - `self` keyword -> address opcode (value)
        - Local variables (params, locals) -> memory pointer (location)
        - Module constants -> evaluate constant expression
        - Immutables -> iload or mload depending on context (value)
        """
        node = self.node
        assert isinstance(node, vy_ast.Name)
        varname = node.id

        # Case 1: "self" keyword -> address opcode
        if varname == "self":
            return VyperValue.from_stack_op(self.builder.address(), AddressT())

        # Get variable info from semantic analysis
        varinfo = node._expr_info.var_info
        assert varinfo is not None

        # Case 2: Local variable in context.variables
        # Return pointer, caller will unwrap if needed
        if varname in self.ctx.variables:
            var = self.ctx.lookup(varname)
            if var.is_pointer_cell:
                return self.ctx.load_pointer_cell_value(var)
            return var.value

        # Case 3: Module constant - recursively lower the constant's value
        if varinfo.is_constant:
            return Expr(varinfo.decl_node.value, self.ctx).lower()

        # Case 4: Immutable - IMMUTABLES location
        if varinfo.is_immutable:
            typ = node._metadata["type"]
            ptr = Ptr(
                operand=IRLiteral(varinfo.position.position), location=DataLocation.IMMUTABLES
            )
            return VyperValue.from_ptr(ptr, typ)

        raise CompilerPanic(f"Unknown variable: {varname}")  # pragma: nocover

    def lower_Attribute(self) -> VyperValue:
        """Lower attribute access.

        Handles:
        - Flag constants (MyFlag.VALUE) → value
        - Address properties (.balance, .codesize, .codehash, etc.) → value
        - Environment variables (msg.sender, block.timestamp, etc.) → value
        - State variables (self.x) → location (STORAGE/CODE/MEMORY)
        - Struct fields (x.field) → location (inherited from base)
        - Interface address (x.address) → value
        """
        node = self.node
        assert isinstance(node, vy_ast.Attribute)
        typ = node._metadata["type"]

        # Case 1: Flag constants (MyFlag.VALUE)
        if isinstance(typ, FlagT):
            value_typ = node.value._metadata.get("type")
            # Check if this is a flag type access (e.g., MyFlag.VALUE)
            # value_typ is TYPE_T(FlagT), not FlagT directly
            if value_typ is not None and is_type_t(value_typ, FlagT):
                flag_id = typ._flag_members[node.attr]
                value = 2**flag_id  # 0 => 1, 1 => 2, 2 => 4, etc.
                return VyperValue.from_stack_op(IRLiteral(value), typ)

        attr = node.attr
        sub_typ = node.value._metadata["type"]

        # Case 2: Struct field access (point.x)
        if isinstance(sub_typ, StructT) and attr in sub_typ.member_types:
            return self._lower_struct_field()

        # Case 3: Address properties
        if attr == "balance":
            sub = Expr(node.value, self.ctx).lower_value()
            return VyperValue.from_stack_op(self.builder.balance(sub), UINT256_T)

        if attr == "codesize":
            if isinstance(node.value, vy_ast.Name) and node.value.id == "self":
                return VyperValue.from_stack_op(self.builder.codesize(), UINT256_T)
            sub = Expr(node.value, self.ctx).lower_value()
            return VyperValue.from_stack_op(self.builder.extcodesize(sub), UINT256_T)

        if attr == "is_contract":
            sub = Expr(node.value, self.ctx).lower_value()
            codesize = self.builder.extcodesize(sub)
            return VyperValue.from_stack_op(self.builder.gt(codesize, IRLiteral(0)), BoolT())

        if attr == "codehash":
            sub = Expr(node.value, self.ctx).lower_value()
            return VyperValue.from_stack_op(self.builder.extcodehash(sub), BYTES32_T)

        # .code on address materializes the full runtime code as Bytes[INF].
        # Struct fields named "code" are handled above before this address check.
        if attr == "code" and isinstance(node.value._metadata.get("type"), AddressT):
            if isinstance(node.value, vy_ast.Name) and node.value.id == "self":
                length = self.builder.codesize()
                return self.ctx.materialize_code_bytes(
                    IRLiteral(0), length, typ, annotation="self.code"
                )
            address = Expr(node.value, self.ctx).lower_value()
            length = self.builder.extcodesize(address)
            return self.ctx.materialize_code_bytes(
                IRLiteral(0), length, typ, address=address, annotation="addr.code"
            )

        # Case 4: Environment variables (msg.*, block.*, tx.*, chain.*)
        if isinstance(node.value, vy_ast.Name) and node.value.id in ENVIRONMENT_VARIABLES:
            if node.value.id == "msg" and attr == "data":
                length = self.builder.calldatasize()
                return self.ctx.materialize_calldata_bytes(
                    IRLiteral(0), length, typ, annotation="msg.data"
                )
            return VyperValue.from_stack_op(self._lower_environment_attr(), typ)

        # Case 5: State variables (self.x)
        varinfo = node._expr_info.var_info
        if varinfo is not None:
            # Constant state variable - evaluate the constant expression
            if varinfo.is_constant:
                return Expr(varinfo.decl_node.value, self.ctx).lower()

            # Immutable state variable
            if varinfo.is_immutable:
                ptr = Ptr(
                    operand=IRLiteral(varinfo.position.position), location=DataLocation.IMMUTABLES
                )
                return VyperValue.from_ptr(ptr, typ)

            # Regular storage/transient variable - return location, don't load!
            slot = varinfo.position.position
            ptr = Ptr(operand=IRLiteral(slot), location=varinfo.location)
            return VyperValue.from_ptr(ptr, typ)

        # Case 6: Interface address (x.address where x is an interface)
        if isinstance(sub_typ, InterfaceT) and attr == "address":
            return VyperValue.from_stack_op(Expr(node.value, self.ctx).lower_value(), AddressT())

        raise CompilerPanic(f"Unsupported attribute access: {node.attr}")  # pragma: nocover

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
        if key == "msg.data":  # pragma: nocover
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

        raise CompilerPanic(f"Unknown environment variable: {key}")  # pragma: nocover

    # === Ternary Expression ===

    def lower_IfExp(self) -> VyperValue:
        """Lower ternary expression: x if cond else y"""
        node = self.node
        assert isinstance(node, vy_ast.IfExp)

        cond = Expr(node.test, self.ctx).lower_value()
        cond_block = self.builder.current_block

        then_block = self.builder.create_block("ternary_then")
        else_block = self.builder.create_block("ternary_else")

        # Pre-allocate result variable
        result = self.builder.new_variable()

        # Process then branch
        self.builder.append_block(then_block)
        self.builder.set_block(then_block)
        then_val = Expr(node.body, self.ctx).lower_value()
        then_block_finish = self.builder.current_block
        then_block_finish.append_instruction("assign", then_val, ret=result)

        # Process else branch
        self.builder.append_block(else_block)
        self.builder.set_block(else_block)
        else_val = Expr(node.orelse, self.ctx).lower_value()
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

        result_typ = node._metadata["type"]
        if result_typ._is_prim_word:
            return VyperValue.from_stack_op(result, result_typ)
        return self._make_ptr_value(result, DataLocation.MEMORY, result_typ)

    # === Subscript Operations ===

    def lower_Subscript(self) -> VyperValue:
        """Lower subscript access: array[index], mapping[key], or tuple[N].

        Returns VyperValue.from_ptr() with element pointer and location.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base_typ = node.value._metadata["type"]

        if isinstance(base_typ, HashMapT):
            return self._lower_mapping_subscript()
        elif isinstance(base_typ, (SArrayT, DArrayT)):
            return self._lower_array_subscript()
        elif isinstance(base_typ, (StructT, TupleT)):
            # Tuple access on struct/tuple (struct[0], tuple[1], etc.)
            return self._lower_tuple_subscript()
        else:  # pragma: nocover
            raise CompilerPanic(f"Unsupported subscript on {base_typ}")

    def _lower_array_subscript(self, bounds_check: bool = True) -> VyperValue:
        """Lower array[index] access.

        Computes element pointer with bounds checking:
        - Static arrays: bounds check against compile-time count
        - Dynamic arrays: load length from first word, skip 32/1 for data

        Returns VyperValue.from_ptr() with element pointer and inherited location.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base_vv = Expr(node.value, self.ctx).lower()
        base = base_vv.operand  # Extract pointer for address math
        index = Expr(node.slice, self.ctx).lower_value()  # Need the value

        base_typ = node.value._metadata["type"]
        elem_typ = base_typ.value_type
        index_typ = node.slice._metadata["type"]

        # Propagate location from base (storage/memory/transient)
        data_loc = base_vv.location
        assert data_loc is not None
        word_scale = 1 if data_loc in (DataLocation.STORAGE, DataLocation.TRANSIENT) else 32

        elem_size = elem_typ.get_size_in(data_loc)

        # Bounds checking
        if bounds_check:
            length: IROperand = IRLiteral(0)
            if isinstance(base_typ, DArrayT):
                # Dynamic array: load length from first word.
                length = self.ctx.load_word(base, data_loc)
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

        return self._make_ptr_value(elem_ptr, data_loc, elem_typ)

    def _lower_mapping_subscript(self) -> VyperValue:
        """Lower mapping[key] access.

        Computes storage slot via keccak256(slot || key):
        - Simple keys (int, address, bytes32): use directly
        - Complex keys (bytes, string): pre-hash with keccak256

        Returns VyperValue.from_ptr() with storage slot and value type.
        Mappings are always in storage.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base_vv = Expr(node.value, self.ctx).lower()
        base = base_vv.operand  # Extract slot for hash computation
        map_typ = node.value._metadata["type"]
        key_typ = map_typ.key_type
        value_typ = map_typ.value_type

        # Handle bytes/string keys - need to hash them first
        if isinstance(key_typ, _BytestringT):
            key = self._lower_keccak256_key(node.slice)
        else:
            key = Expr(node.slice, self.ctx).lower_value()

        # sha3_64(base, key) = keccak256(base || key)
        # Both are 32 bytes, concatenated and hashed
        buf = self.ctx.allocate_buffer(64, "sha3_64")
        ptr = buf.base_ptr()
        self.ctx.ptr_store(ptr, base)
        self.ctx.ptr_store(self.ctx.add_offset(ptr, 32), key)
        slot = self.builder.sha3(ptr.operand, IRLiteral(64))

        # Preserve location from base (storage or transient)
        location = base_vv.location
        assert location is not None
        ptr = Ptr(operand=slot, location=location)
        return VyperValue.from_ptr(ptr, value_typ)

    def _lower_keccak256_key(self, key_node: vy_ast.VyperNode) -> IROperand:
        """Hash a bytes/string key for use as mapping key.

        For bytes32: mstore to scratch, sha3
        For bytes/string: ensure in memory, sha3 data portion
        """
        key_typ = key_node._metadata["type"]

        if key_typ == BYTES32_T:
            # bytes32: mstore to temp buffer and hash
            key = Expr(key_node, self.ctx).lower_value()
            buf = self.ctx.allocate_buffer(32, "mapping_key")
            self.ctx.ptr_store(buf.base_ptr(), key)
            return self.builder.sha3(buf._ptr, IRLiteral(32))

        # bytes/string: get pointer, hash the data portion
        # sha3 only works on memory - copy non-memory data first
        key_vv = Expr(key_node, self.ctx).lower()
        key_typ = key_node._metadata["type"]
        assert isinstance(key_typ, _BytestringT)
        key_mem = self.ctx.ensure_bytestring_in_memory(key_vv, key_typ)
        data_ptr_op = self.ctx.bytes_data_ptr(key_mem)
        length = self.ctx.bytestring_length(key_mem)
        return self.builder.sha3(data_ptr_op, length)

    def _get_bytestring_hash(self, node: vy_ast.VyperNode) -> IROperand:
        """Get keccak256 hash of a bytestring for comparison.

        For constant literals (Str, Bytes), compute hash at compile time.
        This avoids memory allocation issues where loop body literals
        share memory with init phase literals.

        For variables, compute hash at runtime.
        """
        reduced = node.reduced()

        # Check if it's a constant literal we can hash at compile time
        if isinstance(reduced, vy_ast.Str):
            # String literal: encode to bytes and hash the raw bytes
            bytez = reduced.value.encode("utf-8")
            hash_val = int.from_bytes(keccak256(bytez), "big")
            return IRLiteral(hash_val)

        if isinstance(reduced, vy_ast.Bytes):
            # Bytes literal: hash the raw bytes
            bytez = reduced.value
            hash_val = int.from_bytes(keccak256(bytez), "big")
            return IRLiteral(hash_val)

        # Not a constant - compute at runtime
        vv = Expr(node, self.ctx).lower()
        assert isinstance(node, vy_ast.ExprNode)
        typ = node._expr_info.typ
        assert isinstance(typ, _BytestringT)
        vv_mem = self.ctx.ensure_bytestring_in_memory(vv, typ)
        data_ptr_op = self.ctx.bytes_data_ptr(vv_mem)
        length = self.ctx.bytestring_length(vv_mem)
        return self.builder.sha3(data_ptr_op, length)

    def _lower_tuple_subscript(self) -> VyperValue:
        """Lower tuple[N] or struct[N] access.

        Index must be a compile-time constant. Computes offset by summing
        sizes of preceding elements.

        Returns VyperValue.from_ptr() with element pointer and inherited location.
        """
        node = self.node
        assert isinstance(node, vy_ast.Subscript)
        base_vv = Expr(node.value, self.ctx).lower()
        base = base_vv.operand  # Extract pointer for address math
        base_typ = node.value._metadata["type"]

        # Get the compile-time index
        reduced_slice = node.slice.reduced()
        assert isinstance(reduced_slice, vy_ast.Int)
        index = reduced_slice.value

        if self.ctx.is_dynamic_tuple_frame_type(base_typ):
            assert isinstance(base, IRVariable)
            return self.ctx.dynamic_tuple_frame_values(base, base_typ, annotation="subscript")[
                index
            ]

        # Propagate location from base
        data_loc = base_vv.location
        assert data_loc is not None

        # Compute offset by summing sizes of preceding elements
        attrs = list(base_typ.tuple_keys())
        elem_typ = base_typ.member_types[attrs[index]]
        offset = 0
        for i in range(index):
            t = base_typ.member_types[attrs[i]]
            offset += t.get_size_in(data_loc)

        elem_ptr = self.builder.add(base, IRLiteral(offset))

        return self._make_ptr_value(elem_ptr, data_loc, elem_typ)

    def _lower_struct_field(self) -> VyperValue:
        """Lower struct.field access.

        Computes field pointer by summing sizes of preceding fields.

        Returns VyperValue.from_ptr() with field pointer and inherited location.
        """
        node = self.node
        assert isinstance(node, vy_ast.Attribute)
        base_vv = Expr(node.value, self.ctx).lower()
        base = base_vv.operand  # Extract pointer for address math
        base_typ = node.value._metadata["type"]
        attr = node.attr

        # Propagate location from base
        data_loc = base_vv.location
        assert data_loc is not None

        # Find field index and compute offset
        attrs = list(base_typ.tuple_keys())
        field_index = attrs.index(attr)
        field_typ = base_typ.member_types[attr]

        offset = 0
        for i in range(field_index):
            t = base_typ.member_types[attrs[i]]
            offset += t.get_size_in(data_loc)

        field_ptr = self.builder.add(base, IRLiteral(offset))

        return self._make_ptr_value(field_ptr, data_loc, field_typ)

    def _make_ptr_value(self, operand: IROperand, location: DataLocation, typ) -> VyperValue:
        """Create a VyperValue with Ptr for a computed pointer.

        For MEMORY locations, creates a dummy buffer since we don't track buffer provenance
        through pointer arithmetic. For other locations, creates a simple Ptr.
        """
        if location == DataLocation.MEMORY:
            # Buffer requires IRVariable; memory pointers from arithmetic ops are always IRVariables
            assert isinstance(operand, IRVariable)
            size = None if self.ctx.is_unbounded_sequence_type(typ) else typ.memory_bytes_required
            buf = Buffer(_ptr=operand, size=size, annotation="computed_ptr")
            ptr = Ptr(operand=operand, location=location, buf=buf)
        else:
            ptr = Ptr(operand=operand, location=location)
        return VyperValue.from_ptr(ptr, typ)

    def _lower_list_literal_membership(
        self, needle: IROperand, list_node: vy_ast.List, is_in: bool
    ) -> IROperand:
        """Lower membership test for list literals: x in [a, b, c].

        Unrolls to:
        - For 'in': (x == a) or (x == b) or (x == c)
        - For 'not in': (x != a) and (x != b) and (x != c)

        More efficient than loop for compile-time known list literals.

        NOTE: All elements are evaluated FIRST before any comparisons,
        so side effects are NOT short-circuited. This matches legacy
        behavior (expr.py:486 does unwrap_location on ALL elements first).
        The or_/and_ IR ops combine already-computed results.
        """
        # Block non-primitive element types (mirrors legacy codegen)
        # See issue #2637 for context
        elem_typ = list_node._metadata["type"].value_type
        if not elem_typ._is_prim_word:  # pragma: nocover
            raise TypeMismatch(
                "`in` not allowed for arrays of non-base types, tracked in issue #2637", self.node
            )

        b = self.builder

        if not list_node.elements:
            # Empty list: x in [] is always False, x not in [] is always True
            return IRLiteral(0 if is_in else 1)

        # Evaluate ALL elements first to preserve side effects
        elem_vals = [Expr(elem, self.ctx).lower_value() for elem in list_node.elements]

        # Then build comparison chain
        comparisons = [b.eq(needle, elem_val) for elem_val in elem_vals]

        # Combine comparisons
        if is_in:
            # x in [a, b, c] = (x == a) or (x == b) or (x == c)
            result = comparisons[0]
            for cmp in comparisons[1:]:
                result = b.or_(result, cmp)
        else:
            # x not in [a, b, c] = (x != a) and (x != b) and (x != c)
            # = iszero(eq(x, a)) and iszero(eq(x, b)) and ...
            result = b.iszero(comparisons[0])
            for cmp in comparisons[1:]:
                result = b.and_(result, b.iszero(cmp))

        return result

    def _lower_array_membership(
        self, needle: IROperand, haystack_vv: VyperValue, haystack_typ, is_in: bool
    ) -> IRVariable:
        """Lower array membership test: x in array or x not in array.

        Uses a loop with early break:
        - result = 0 (not found)
        - for each element:
            - if element == needle: result = 1, break
        - return result (or iszero(result) for not in)
        """
        # Block non-primitive element types (mirrors legacy codegen)
        # See issue #2637 for context
        elem_typ = haystack_typ.value_type
        if not elem_typ._is_prim_word:  # pragma: nocover
            raise TypeMismatch(
                "`in` not allowed for arrays of non-base types, tracked in issue #2637", self.node
            )

        haystack = haystack_vv.operand
        location = haystack_vv.location
        assert location is not None

        # Determine word scale based on location
        # Storage: 1 slot per word, Memory: 32 bytes per word
        word_scale = 1 if location in (DataLocation.STORAGE, DataLocation.TRANSIENT) else 32

        # Get array properties
        length: IROperand
        if isinstance(haystack_typ, DArrayT):
            length = self.ctx.load_word(haystack, location)
            bound = haystack_typ.count
            offset_base = word_scale * DYNAMIC_ARRAY_OVERHEAD
        elif isinstance(haystack_typ, SArrayT):
            length = IRLiteral(haystack_typ.count)
            bound = haystack_typ.count
            offset_base = 0
        else:  # pragma: nocover
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
        if isinstance(haystack_typ, DArrayT) and is_bounded_length(bound):
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
        elem_val = self.ctx.load_word(elem_addr, location)
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

    def lower_Call(self) -> VyperValue:
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

        # Check if this is an internal call (self.func() or module.func())
        if isinstance(func_t, ContractFunctionT):
            if func_t.is_internal or func_t.is_constructor:
                return self._lower_internal_call()

        # Built-in functions
        # Builtins may return VyperValue (memory-located) or IROperand (stack values)
        if isinstance(func_t, BuiltinFunctionT):
            result = self._lower_builtin_call(func_t)
            if isinstance(result, VyperValue):
                return result
            result_typ = node._metadata["type"]
            return VyperValue.from_stack_op(result, result_typ)

        # Struct constructor: MyStruct(field1=val1, field2=val2)
        if func_t is not None and is_type_t(func_t, StructT):
            return self._lower_struct_constructor()

        # Interface constructor: MyInterface(<address>) or module.__at__(<address>)
        if func_t is not None and is_type_t(func_t, InterfaceT):
            return self._lower_interface_constructor()

        # Intrinsic interface constructor: module.__at__(<address>)
        if isinstance(func, vy_ast.Attribute) and func.attr == "__at__":
            return self._lower_interface_constructor()

        # DynArray methods: arr.append(val), arr.pop()
        if isinstance(func_t, MemberFunctionT):
            return self._lower_member_function_call(func_t)

        raise CompilerPanic(f"Unsupported call: {node.func}")  # pragma: nocover

    def _lower_internal_call(self) -> VyperValue:
        """Lower internal function call (self.func(...)).

        Calling convention:
        1. Allocate return buffer if needed
        2. Store memory-passed args to temporary buffers
        3. Load stack-passed args to stack
        4. Emit invoke instruction
        5. For multi-return, copy stack outputs to caller memory
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func_name = node.func.attr

        # Get function type from the function attribute's metadata
        # node._metadata["type"] is the return type, we need the function type
        func_t = node.func._metadata["type"].get_concrete_override()
        assert func_name == func_t.name

        # Check constancy: can't call mutable internal functions from view/pure contexts
        if self.ctx.is_constant() and func_t.is_modifying:
            raise StateAccessViolation(
                f"May not call state modifying function "
                f"'{func_name}' within {self.ctx.pp_constancy()}.",
                node,
            )

        returns_count = returns_stack_count(func_t)
        dynamic_returns_count = returns_dynamic_count(func_t)
        pass_via_stack_dict = pass_via_stack(func_t)

        # Generate function label
        # Format: "internal {function_id} {name}({arg_types})_runtime"
        suffix = "_deploy" if self.ctx.is_ctor_context else "_runtime"
        argz = ",".join([str(arg.typ) for arg in func_t.arguments])
        target_label = f"internal {func_t._function_id} {func_name}({argz}){suffix}"

        # Allocate return buffer
        return_buf: Optional[IROperand] = None
        if func_t.return_type is not None:
            if self.ctx.is_dynamic_tuple_frame_type(func_t.return_type):
                pass
            elif returns_count > 0:
                # Multi-return: allocate scratch buffer
                return_buf = self.builder.alloca(32 * returns_count)
            elif dynamic_returns_count == 0:
                # Memory return: allocate buffer for full return type
                return_buf = self.ctx.new_temporary_value(func_t.return_type).operand

        # Prepare arguments
        invoke_args: list[IROperand] = []  # Stack args for invoke

        # First: return buffer pointer if memory return (not multi-return)
        if return_buf is not None and returns_count == 0:
            invoke_args.append(return_buf)

        # Evaluate and stage arguments (including defaults for unprovided kwargs)
        # Get default values for unprovided kwargs
        num_provided = len(node.args)
        num_provided_kwargs = num_provided - func_t.n_positional_args
        unprovided_kwargs = func_t.keyword_args[num_provided_kwargs:]
        default_nodes = [kwarg.default_value for kwarg in unprovided_kwargs]
        all_arg_nodes = list(node.args) + default_nodes

        # IMPORTANT: Evaluate ALL arguments first before allocating staging buffers.
        # If arguments contain nested internal calls, those calls may use the callee's
        # frame which can overlap with our staging buffers (due to memory reuse).
        # By evaluating all args first, we ensure nested calls complete before we
        # allocate staging buffers, avoiding corruption.
        # See legacy codegen: vyper/codegen/self_call.py (contains_self_call handling)
        arg_vals: list[VyperValue] = []
        for arg_node in all_arg_nodes:
            arg_vals.append(Expr(arg_node, self.ctx).lower())

        # Now allocate staging buffers and copy evaluated values
        for i, arg_val in enumerate(arg_vals):
            arg_t = func_t.arguments[i]
            arg_op = self.ctx.unwrap(arg_val)

            if pass_via_stack_dict[arg_t.name]:
                # Stack-passed arg: use value directly
                # For struct/tuple types that fit in one word, arg_val is a memory
                # pointer (from unwrap), so we need to load the actual value
                if hasattr(arg_t.typ, "tuple_items"):
                    assert isinstance(arg_op, IRVariable)
                    arg_op = self.builder.mload(arg_op)
                invoke_args.append(arg_op)
            else:
                # Memory-passed arg: allocate buffer, copy value, pass pointer.
                # Backend passes can forward safe readonly arguments.
                if self.ctx.is_unbounded_sequence_type(arg_t.typ):
                    buf_val = self.ctx.copy_sequence_to_scratch(
                        arg_val, arg_t.typ, annotation=arg_t.name
                    )
                else:
                    buf_val = self.ctx.new_temporary_value(arg_t.typ)
                    assert isinstance(buf_val.operand, IRVariable)
                    self.ctx.store_vyper_value(arg_val, buf_val.operand, arg_t.typ)
                invoke_args.append(buf_val.operand)

        # Emit invoke instruction
        invoke_returns_count = returns_count + dynamic_returns_count
        if invoke_returns_count > 0:
            outs = self.builder.invoke(
                IRLabel(target_label), invoke_args, returns=invoke_returns_count
            )
            if dynamic_returns_count > 0:
                assert func_t.return_type is not None
                if self.ctx.is_dynamic_tuple_frame_type(func_t.return_type):
                    assert isinstance(func_t.return_type, TupleT)
                    return self.ctx.dynamic_tuple_frame_from_outputs(
                        outs, func_t.return_type, annotation=func_name
                    )

                assert returns_count == 0
                assert len(outs) == 1
                # Dynamic internal returns publish a runtime memory pointer directly.
                return self.ctx.dynamic_memory_value(
                    outs[0], func_t.return_type, annotation=func_name
                )

            # Copy stack returns to buffer
            assert return_buf is not None
            assert isinstance(return_buf, IRVariable)
            for i, outv in enumerate(outs):
                dst = self.builder.add(return_buf, IRLiteral(i * 32))
                self.builder.mstore(dst, outv)
        else:
            self.builder.invoke(IRLabel(target_label), invoke_args, returns=0)

        # Return the return buffer as a location, or void
        if return_buf is not None:
            return self._make_ptr_value(return_buf, DataLocation.MEMORY, func_t.return_type)

        return VyperValue.from_stack_op(IRLiteral(0), VOID_TYPE)  # void return

    # === Builtin Function Calls ===

    def _lower_builtin_call(self, func_t: BuiltinFunctionT) -> "IROperand | VyperValue":
        """Dispatch builtin function calls to handlers in builtins/ submodule.

        Returns IROperand for stack values, VyperValue for memory-located results.
        """
        from vyper.codegen_venom.builtins import lower_builtin

        return lower_builtin(func_t._id, self.node, self.ctx)

    # === Constructor and Member Function Calls ===

    def _lower_struct_constructor(self) -> VyperValue:
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
        val = self.ctx.new_temporary_value(struct_t)
        assert isinstance(val.operand, IRVariable)

        # Build map of field name -> value node from keywords
        member_vals = {}
        for kwarg in node.keywords:
            member_vals[kwarg.arg] = kwarg.value

        # Store each field at its correct offset (in struct field order)
        offset = 0
        for field_name in struct_t.tuple_keys():
            field_typ = struct_t.member_types[field_name]
            field_vv = Expr(member_vals[field_name], self.ctx).lower()

            dst = self.builder.add(val.operand, IRLiteral(offset))

            self.ctx.store_vyper_value(field_vv, dst, field_typ)
            offset += field_typ.memory_bytes_required

        return val

    def _lower_interface_constructor(self) -> VyperValue:
        """Lower interface constructor call: MyInterface(<address>).

        Returns the address value - interface types are just addresses at runtime.
        The type annotation is used by the type system but doesn't affect codegen.
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        # Interface constructor takes exactly one argument: the address
        assert len(node.args) == 1
        result_typ = node._metadata["type"]
        return VyperValue.from_stack_op(Expr(node.args[0], self.ctx).lower_value(), result_typ)

    def _lower_member_function_call(self, func_t: MemberFunctionT) -> VyperValue:
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
        else:  # pragma: nocover
            raise CompilerPanic(f"Unknown member function: {attr}")

    def _lower_dynarray_append(self) -> VyperValue:
        """Lower DynArray.append(val).

        1. For non-primitive elements, stage arg to a temporary buffer
           (conservative alias guard)
        2. Load current length
        4. Assert length < capacity (bounds check)
        5. Compute element pointer: data_ptr + length * elem_size
        6. Store element
        7. Increment and store new length

        Reference: vyper/codegen/core.py:append_dyn_array
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func = node.func
        darray_node = func.value  # The DynArray being appended to
        darray_typ = darray_node._metadata["type"]
        elem_typ = darray_typ.value_type

        if self.ctx.is_unbounded_dynarray_type(darray_typ):
            return self._lower_unbounded_dynarray_append()

        # Get the array VyperValue
        darray_vv = Expr(darray_node, self.ctx).lower()
        darray_ptr = darray_vv.operand

        # Get the element value.
        # For complex elements, always stage through a temporary buffer to
        # guard against aliasing cases like arr.append(arr[0]). Backend passes
        # can elide the staging copy when it is provably redundant.
        assert len(node.args) == 1
        arg_node = node.args[0]

        arg_vv = Expr(arg_node, self.ctx).lower()
        arg_val = self.ctx.unwrap(arg_vv)
        elem_src_typ = arg_vv.typ

        if not elem_typ._is_prim_word:
            # Always stage complex elements through a temp buffer to guard
            # against aliasing (e.g. arr.append(arr[0])).
            # MemoryCopyElisionPass eliminates the copy when safe.
            temp_buf = self.ctx.new_temporary_value(elem_typ)
            assert isinstance(temp_buf.operand, IRVariable)
            self.ctx.store_vyper_value(arg_vv, temp_buf.operand, elem_typ)
            elem_val: IROperand = temp_buf.operand
            elem_src_typ = elem_typ
        else:
            elem_val = arg_val

        # Get location from VyperValue
        data_loc = darray_vv.location
        assert data_loc is not None
        word_scale = 1 if data_loc in (DataLocation.STORAGE, DataLocation.TRANSIENT) else 32

        if (
            data_loc in (DataLocation.STORAGE, DataLocation.TRANSIENT)
            and not elem_typ._is_prim_word
            and elem_src_typ != elem_typ
        ):
            # Normalize source layout for locations that only understand destination layout.
            normalized = self.ctx.new_temporary_value(elem_typ)
            assert isinstance(normalized.operand, IRVariable)
            self.ctx.store_memory(elem_val, normalized.operand, elem_typ, src_typ=elem_src_typ)
            elem_val = normalized.operand
            elem_src_typ = elem_typ

        elem_size = elem_typ.get_size_in(data_loc)
        capacity = darray_typ.count  # Maximum length

        # 1. Load current length
        length = self.builder.load(darray_ptr, data_loc)

        # 2. Assert length < capacity
        if is_bounded_length(capacity):
            valid = self.builder.lt(length, IRLiteral(capacity))
            self.builder.assert_(valid)

        # 3. Compute element pointer: data_ptr + length * elem_size
        overhead = word_scale * DYNAMIC_ARRAY_OVERHEAD
        data_ptr = self.builder.add(darray_ptr, IRLiteral(overhead))
        offset = self.builder.mul(length, IRLiteral(elem_size))
        elem_ptr = self.builder.add(data_ptr, offset)

        # 4. Store element - handle complex types properly
        # For primitive types, use single-word store
        # For complex types, elem_val is a memory pointer - need to copy data
        if elem_typ._is_prim_word:
            self.builder.store(elem_ptr, elem_val, data_loc)
        elif data_loc == DataLocation.MEMORY:
            self.ctx.store_memory(elem_val, elem_ptr, elem_typ, src_typ=elem_src_typ)
        elif data_loc == DataLocation.STORAGE:
            self.ctx.store_storage(elem_val, elem_ptr, elem_typ)
        elif data_loc == DataLocation.TRANSIENT:
            self.ctx.store_transient(elem_val, elem_ptr, elem_typ)
        else:  # pragma: nocover
            raise CompilerPanic(f"Unsupported location for append: {data_loc}")

        # 5. Increment and store new length
        new_length = self.builder.add(length, IRLiteral(1))
        self.builder.store(darray_ptr, new_length, data_loc)

        # append() returns nothing
        return VyperValue.from_stack_op(IRLiteral(0), VOID_TYPE)

    def _lower_unbounded_dynarray_append(self) -> VyperValue:
        """Lower append on exact-sized DynArray[..., INF] pointer-cell locals."""
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        assert len(node.args) == 1

        darray_node = node.func.value
        darray_typ = darray_node._metadata["type"]
        assert isinstance(darray_typ, DArrayT)
        elem_typ = darray_typ.value_type

        if not isinstance(darray_node, vy_ast.Name):
            raise CompilerPanic("append on unbounded DynArray requires a local variable")

        var = self.ctx.lookup(darray_node.id)
        if not var.is_pointer_cell:
            raise CompilerPanic("append on unbounded DynArray requires pointer-cell storage")

        arg_vv = Expr(node.args[0], self.ctx).lower()
        arg_val = self.ctx.unwrap(arg_vv)
        elem_src_typ = arg_vv.typ

        if not elem_typ._is_prim_word:
            temp_buf = self.ctx.new_temporary_value(elem_typ)
            assert isinstance(temp_buf.operand, IRVariable)
            self.ctx.store_vyper_value(arg_vv, temp_buf.operand, elem_typ)
            elem_val: IROperand = temp_buf.operand
            elem_src_typ = elem_typ
        else:
            elem_val = arg_val

        old_ptr = self.ctx.ptr_load(var.value.ptr())
        assert isinstance(old_ptr, IRVariable)
        length = self.builder.mload(old_ptr)
        elem_size = elem_typ.memory_bytes_required

        old_size = self.ctx.dynarray_runtime_size_from_length(length, darray_typ)
        data_size = self.builder.sub(old_size, IRLiteral(32))
        new_size = self.ctx.checked_add(old_size, IRLiteral(elem_size))

        new_ptr = self.ctx.allocate_scratch(new_size)
        self.ctx.copy_memory_dynamic(new_ptr, old_ptr, old_size)

        data_ptr = self.builder.add(new_ptr, IRLiteral(32))
        elem_ptr = self.builder.add(data_ptr, data_size)
        if elem_typ._is_prim_word:
            self.builder.mstore(elem_ptr, elem_val)
        else:
            self.ctx.store_memory(elem_val, elem_ptr, elem_typ, src_typ=elem_src_typ)

        new_length = self.builder.add(length, IRLiteral(1))
        no_length_wrap = self.builder.gt(new_length, length)
        self.builder.assert_(no_length_wrap)
        self.builder.mstore(new_ptr, new_length)
        self.ctx.ptr_store(var.value.ptr(), new_ptr)
        return VyperValue.from_stack_op(IRLiteral(0), VOID_TYPE)

    def _lower_dynarray_pop(self) -> VyperValue:
        """Lower DynArray.pop().

        1. Load current length
        2. Assert length > 0 (can't pop empty)
        3. Compute new_length = length - 1
        4. Store new length
        5. Return element at new_length index (the popped element)

        Reference: vyper/codegen/core.py:pop_dyn_array
        """
        node = self.node
        assert isinstance(node, vy_ast.Call)
        assert isinstance(node.func, vy_ast.Attribute)
        func = node.func
        darray_node = func.value  # The DynArray being popped from
        darray_typ = darray_node._metadata["type"]
        elem_typ = darray_typ.value_type

        # Get the array VyperValue
        darray_vv = Expr(darray_node, self.ctx).lower()
        darray_ptr = darray_vv.operand

        # Get location from VyperValue
        data_loc = darray_vv.location
        assert data_loc is not None
        word_scale = 1 if data_loc in (DataLocation.STORAGE, DataLocation.TRANSIENT) else 32

        elem_size = elem_typ.get_size_in(data_loc)

        # 1. Load current length
        length = self.builder.load(darray_ptr, data_loc)

        # 2. Assert length > 0 (can't pop empty array)
        valid = self.builder.iszero(self.builder.iszero(length))
        self.builder.assert_(valid)

        # 3. Compute new_length = length - 1
        new_length = self.builder.sub(length, IRLiteral(1))

        # 4. Store new length
        self.builder.store(darray_ptr, new_length, data_loc)

        # 5. Return element at new_length index (the popped element)
        overhead = word_scale * DYNAMIC_ARRAY_OVERHEAD
        data_ptr = self.builder.add(darray_ptr, IRLiteral(overhead))
        offset = self.builder.mul(new_length, IRLiteral(elem_size))
        elem_ptr = self.builder.add(data_ptr, offset)

        # Return as location - unwrap() will load for primitives
        return self._make_ptr_value(elem_ptr, data_loc, elem_typ)

    # === External Calls ===

    def lower_ExtCall(self) -> VyperValue:
        """Lower extcall statement (mutable external call).

        extcall interface.method(args, value=..., gas=...)
        """
        return self._lower_external_call()

    def lower_StaticCall(self) -> VyperValue:
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
        value: IROperand = IRLiteral(0)
        gas: Optional[IROperand] = None
        skip_contract_check = False
        default_return_value: Optional[VyperValue] = None

        for kw in call_node.keywords:
            if kw.arg == "value":
                value = Expr(kw.value, self.ctx).lower_value()
            elif kw.arg == "gas":
                gas = Expr(kw.value, self.ctx).lower_value()
            elif kw.arg == "skip_contract_check":
                kw_val = Expr(kw.value, self.ctx).lower_value()
                # Must be a literal True/False
                if not isinstance(kw_val, IRLiteral):  # pragma: nocover
                    raise CompilerPanic(f"Expected IRLiteral for keyword, got {type(kw_val)}")
                skip_contract_check = bool(kw_val.value)
            elif kw.arg == "default_return_value":
                default_vv = Expr(kw.value, self.ctx).lower()
                # Freeze the expression here; the default block runs after the
                # external call. Primitive values can stay on the stack, but
                # composite values need a fresh memory copy instead of a
                # pointer to a source location that later code may mutate.
                if default_vv.typ._is_prim_word:
                    default_return_value = VyperValue.from_stack_op(
                        self.ctx.unwrap(default_vv), default_vv.typ
                    )
                elif self.ctx.is_dynamic_tuple_frame_type(default_vv.typ):
                    default_return_value = default_vv
                elif self.ctx.is_unbounded_sequence_type(default_vv.typ):
                    default_return_value = self.ctx.copy_sequence_to_scratch(
                        default_vv, default_vv.typ, annotation="external call default_return_value"
                    )
                else:
                    default_return_value = self.ctx.materialize_value(
                        default_vv, annotation="external call default_return_value"
                    )
            else:  # pragma: nocover
                raise CompilerPanic(f"Unexpected keyword argument: {kw.arg}")

        if gas is None:
            gas = self.builder.gas()

        return _CallKwargs(
            value=value,
            gas=gas,
            skip_contract_check=skip_contract_check,
            default_return_value=default_return_value,
        )

    def _external_call_args_need_runtime_encoding(self, arg_vals: list[VyperValue]) -> bool:
        return any(self.ctx.is_unbounded_sequence_type(arg_vv.typ) for arg_vv in arg_vals)

    def _lower_external_call(self) -> VyperValue:
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
        node = self.node
        b = self.builder

        # ExtCall and StaticCall nodes wrap a Call in their .value attribute
        assert isinstance(node, (vy_ast.ExtCall, vy_ast.StaticCall))
        call_node = node.value

        # Get function type from the call expression
        assert isinstance(call_node.func, vy_ast.Attribute)
        fn_type: ContractFunctionT = call_node.func._metadata["type"]

        # get un-wildcard-ed return type
        return_t = call_node._metadata["call_return_type"]
        has_unbounded_return = self.ctx.is_unbounded_sequence_type(return_t)
        has_dynamic_tuple_return = return_t is not None and self.ctx.is_dynamic_tuple_frame_type(
            return_t
        )

        # Evaluate contract address (the interface value)
        contract_address = Expr(call_node.func.value, self.ctx).lower_value()

        # Evaluate arguments.
        arg_vals: list[VyperValue] = []
        for arg in call_node.args:
            arg_vals.append(Expr(arg, self.ctx).lower())

        # Parse kwargs
        call_kwargs = self._parse_external_call_kwargs(call_node)

        # Calculate buffer size needed.
        # Use concrete types from the lowered argument values, not the interface's
        # declared parameter types (which may be WILDCARD for JSON ABI interfaces).
        args_tuple_t = TupleT(tuple(v.typ for v in arg_vals))
        dynamic_args = self._external_call_args_need_runtime_encoding(arg_vals)
        if dynamic_args:
            args_alloc_size = runtime_abi_size_for_encode(self.ctx, arg_vals, args_tuple_t)
        else:
            args_abi_t = args_tuple_t.abi_type
            args_abi_size = args_abi_t.size_bound()
            args_alloc_size = IRLiteral(args_abi_size)

        if return_t is not None:
            if has_unbounded_return or has_dynamic_tuple_return:
                return_abi_size = 0
            else:
                return_abi_t = calculate_type_for_external_return(return_t).abi_type
                return_abi_size = return_abi_t.size_bound()
        else:
            return_abi_size = 0

        # Buffer size: max(args, return) + 32 for method ID padding
        if dynamic_args:
            buf_payload_size = args_alloc_size
            if return_abi_size > 0:
                buf_payload_size = b.select(
                    b.lt(args_alloc_size, IRLiteral(return_abi_size)),
                    IRLiteral(return_abi_size),
                    args_alloc_size,
                )
            buf_ptr = self.ctx.allocate_scratch(
                self.ctx.checked_add(buf_payload_size, IRLiteral(32))
            )
        else:
            buf_size = max(args_abi_size, return_abi_size) + 32
            buf = self.ctx.allocate_buffer(buf_size, annotation="external_call_buf")
            buf_ptr = buf._ptr

        # === Pack Arguments ===
        # Store method ID at buf (right-aligned in 32-byte word, so selector at buf+28)
        # Method ID = first 4 bytes of keccak256(signature)
        abi_signature = fn_type.name + args_tuple_t.abi_type.selector_name()
        method_id = util.method_id_int(abi_signature)
        b.mstore(buf_ptr, IRLiteral(method_id))

        # ABI-encode arguments starting at buf+32
        if len(arg_vals) > 0:
            encode_dst = b.add(buf_ptr, IRLiteral(32))
            if dynamic_args:
                args_abi_len = abi_encode_values_to_buf(
                    self.ctx, encode_dst, arg_vals, args_tuple_t
                )
            else:
                # Create temp buffer for args in memory
                args_val = self.ctx.new_temporary_value(args_tuple_t)
                assert isinstance(args_val.operand, IRVariable)

                # Store each arg at its position in args_buf
                offset = 0
                for arg_vv in arg_vals:
                    arg_typ = arg_vv.typ
                    dst = b.add(args_val.operand, IRLiteral(offset))
                    self.ctx.store_vyper_value(arg_vv, dst, arg_typ)
                    offset += arg_typ.memory_bytes_required

                # ABI-encode from args_buf to buf+32
                abi_encode_to_buf(self.ctx, encode_dst, args_val.operand, args_tuple_t)
                args_abi_len = IRLiteral(args_abi_size)
        else:
            args_abi_len = IRLiteral(0)

        # Call starts at buf+28, length = 4-byte selector + ABI args payload.
        args_ofst = b.add(buf_ptr, IRLiteral(28))
        args_len = self.ctx.checked_add(args_abi_len, IRLiteral(4))

        # === Contract Existence Check ===
        # If function returns nothing and skip_contract_check is False,
        # check extcodesize before call (can't rely on returndatasize check)
        if return_t is None and not call_kwargs.skip_contract_check:
            codesize = b.extcodesize(contract_address)
            b.assert_(codesize)

        # === Dispatch CALL or STATICCALL ===
        use_staticcall = fn_type.mutability in (StateMutability.VIEW, StateMutability.PURE)

        # Return buffer location and size
        ret_ofst = buf_ptr
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
        dst_buf = self.ctx.allocate_buffer(0)
        b.returndatacopy(dst_buf._ptr, IRLiteral(0), rds)
        b.revert(dst_buf._ptr, rds)

        # Continue block
        b.append_block(cont_bb)
        b.set_block(cont_bb)

        # === Unpack Return Value ===
        if return_t is None:
            return VyperValue.from_stack_op(IRLiteral(0), VOID_TYPE)

        if has_unbounded_return:
            return self._unpack_unbounded_external_call_return(
                call_kwargs, contract_address, return_t
            )
        if has_dynamic_tuple_return:
            assert isinstance(return_t, TupleT)
            return self._unpack_dynamic_tuple_external_call_return(
                call_kwargs, contract_address, return_t
            )

        wrapped_return_t = calculate_type_for_external_return(return_t)
        min_return_size = wrapped_return_t.abi_type.static_size()

        # Allocate result buffer
        result_val = self.ctx.new_temporary_value(wrapped_return_t)
        assert isinstance(result_val.operand, IRVariable)

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

            # Store default value
            default_vv = call_kwargs.default_return_value
            assert default_vv is not None
            self.ctx.store_vyper_value(default_vv, result_val.operand, return_t)

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

            # No returndatacopy needed: staticcall/call already wrote
            # min(returndatasize, ret_len) bytes to buf_ptr, and
            # payload_bound caps reads at ret_len (== size_bound()).

            # Compute hi bound for decode (prevents overread)
            # Cap at return_abi_size to handle truncation case
            max_return_size = wrapped_return_t.abi_type.size_bound()
            payload_bound = b.select(
                b.lt(rds, IRLiteral(max_return_size)), rds, IRLiteral(max_return_size)
            )
            hi = b.add(buf_ptr, payload_bound)
            src = self._make_ptr_value(buf_ptr, DataLocation.MEMORY, wrapped_return_t)
            abi_decode_to_buf(self.ctx, result_val.operand, src, hi=hi)

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

            # No returndatacopy needed: staticcall/call already wrote
            # min(returndatasize, ret_len) bytes to buf_ptr, and
            # payload_bound caps reads at ret_len (== size_bound()).

            # Compute hi bound for decode (prevents overread)
            # Cap at return_abi_size to handle truncation case
            max_return_size = wrapped_return_t.abi_type.size_bound()
            payload_bound = b.select(
                b.lt(rds, IRLiteral(max_return_size)), rds, IRLiteral(max_return_size)
            )
            hi = b.add(buf_ptr, payload_bound)
            src = self._make_ptr_value(buf_ptr, DataLocation.MEMORY, wrapped_return_t)
            abi_decode_to_buf(self.ctx, result_val.operand, src, hi=hi)

        # Return as location in memory with unwrapped type
        # The data is at offset 0 in the wrapped tuple, so pointer is correct
        if needs_external_call_wrap(return_t):
            return VyperValue.from_ptr(result_val.ptr(), return_t)
        return result_val

    def _decode_unbounded_sequence_external_call_member(
        self, return_t: VyperType, src: IRVariable, hi: IROperand
    ) -> VyperValue:
        assert self.ctx.is_unbounded_sequence_type(return_t)
        b = self.builder

        # Check the length word before reading it; payload helpers repeat this
        # bound after `length` is available and then check the full payload.
        length_word_end = b.add(src, IRLiteral(32))
        no_length_end_wrap = b.iszero(b.lt(length_word_end, src))
        b.assert_(no_length_end_wrap)
        length_word_in_bounds = b.iszero(b.gt(length_word_end, hi))
        b.assert_(length_word_in_bounds)

        if self.ctx.is_unbounded_bytestring_type(return_t):
            length = b.mload(src)
            self.ctx.assert_abi_bytes_payload_in_bounds(src, length, hi)
            data_start = b.add(src, IRLiteral(32))
            return self.ctx.materialize_bytes_from_location(
                data_start, length, return_t, DataLocation.MEMORY, annotation="external call return"
            )

        assert isinstance(return_t, DArrayT)
        src_vv = self._make_ptr_value(src, DataLocation.MEMORY, return_t)
        return decode_unbounded_dynarray_to_scratch(
            self.ctx, src_vv, return_t, hi, "external call return"
        )

    def _copy_returndata_to_scratch(
        self, returndata_size: IROperand
    ) -> tuple[IRVariable, IROperand]:
        b = self.builder

        returndata_ptr = self.ctx.allocate_scratch(returndata_size)
        b.returndatacopy(returndata_ptr, IRLiteral(0), returndata_size)

        hi = b.add(returndata_ptr, returndata_size)
        no_hi_wrap = b.iszero(b.lt(hi, returndata_ptr))
        b.assert_(no_hi_wrap)
        return returndata_ptr, hi

    def _copy_and_decode_unbounded_external_call_return(
        self, return_t: VyperType, returndata_size: IROperand
    ) -> VyperValue:
        assert self.ctx.is_unbounded_sequence_type(return_t)
        b = self.builder

        ok = b.iszero(b.lt(returndata_size, IRLiteral(32)))
        b.assert_(ok)

        returndata_ptr, hi = self._copy_returndata_to_scratch(returndata_size)

        # ABI external returns are always encoded as a tuple. A single dynamic
        # bytes/string return is therefore `[offset][length][data...]`.
        offset = b.mload(returndata_ptr)

        src = b.add(returndata_ptr, offset)
        no_src_wrap = b.iszero(b.lt(src, returndata_ptr))
        b.assert_(no_src_wrap)
        assert isinstance(src, IRVariable)
        return self._decode_unbounded_sequence_external_call_member(return_t, src, hi)

    def _copy_and_decode_dynamic_tuple_external_call_return(
        self, return_t: TupleT, returndata_size: IROperand
    ) -> VyperValue:
        assert self.ctx.is_dynamic_tuple_frame_type(return_t)
        b = self.builder

        static_size = return_t.abi_type.static_size()
        ok = b.iszero(b.lt(returndata_size, IRLiteral(static_size)))
        b.assert_(ok)

        returndata_ptr, hi = self._copy_returndata_to_scratch(returndata_size)

        tuple_src = returndata_ptr
        if needs_external_call_wrap(return_t):
            offset = b.mload(returndata_ptr)
            tuple_src = b.add(returndata_ptr, offset)
            no_tuple_src_wrap = b.iszero(b.lt(tuple_src, returndata_ptr))
            b.assert_(no_tuple_src_wrap)

        assert isinstance(tuple_src, IRVariable)
        static_end = b.add(tuple_src, IRLiteral(static_size))
        no_static_end_wrap = b.iszero(b.lt(static_end, tuple_src))
        static_in_bounds = b.iszero(b.gt(static_end, hi))
        b.assert_(b.and_(no_static_end_wrap, static_in_bounds))

        frame = self.ctx.allocate_scratch(IRLiteral(self.ctx.dynamic_tuple_frame_size(return_t)))
        abi_offset = 0
        for i, member_t in enumerate(return_t.member_types):
            static_loc = b.add(tuple_src, IRLiteral(abi_offset))
            if member_t.abi_type.is_dynamic():
                offset = b.mload(static_loc)
                member_src = b.add(tuple_src, offset)
                no_member_src_wrap = b.iszero(b.lt(member_src, tuple_src))
                b.assert_(no_member_src_wrap)
            else:
                member_src = static_loc

            assert isinstance(member_src, IRVariable)
            if self.ctx.is_unbounded_sequence_type(member_t):
                member_vv = self._decode_unbounded_sequence_external_call_member(
                    member_t, member_src, hi
                )
            else:
                member_vv = self.ctx.new_temporary_value(member_t)
                assert isinstance(member_vv.operand, IRVariable)
                src_vv = self._make_ptr_value(member_src, DataLocation.MEMORY, member_t)
                abi_decode_to_buf(self.ctx, member_vv.operand, src_vv, hi=hi)

            cell = b.add(frame, IRLiteral(i * 32))
            if member_t._is_prim_word:
                value = self.ctx.unwrap(member_vv)
            else:
                value = member_vv.operand
            b.mstore(cell, value)
            abi_offset += member_t.abi_type.embedded_static_size()

        return self.ctx.dynamic_tuple_frame_value(
            frame, return_t, annotation="external call return"
        )

    def _unpack_unbounded_external_call_return(
        self, call_kwargs: _CallKwargs, contract_address: IROperand, return_t: VyperType
    ) -> VyperValue:
        b = self.builder
        rds = b.returndatasize()

        if call_kwargs.default_return_value is None:
            return self._copy_and_decode_unbounded_external_call_return(return_t, rds)

        ret_cell = self.ctx.allocate_buffer(32, annotation="external call dynamic return ptr")
        default_bb = b.create_block("extcall_default")
        decode_bb = b.create_block("extcall_decode")
        exit_bb = b.create_block("extcall_exit")

        b.jnz(b.iszero(rds), default_bb.label, decode_bb.label)

        b.append_block(default_bb)
        b.set_block(default_bb)

        default_vv = call_kwargs.default_return_value
        assert default_vv is not None
        default_value = self.ctx.copy_sequence_to_scratch(
            default_vv, return_t, annotation="external call default_return_value"
        )
        b.mstore(ret_cell._ptr, default_value.operand)

        if not call_kwargs.skip_contract_check:
            codesize = b.extcodesize(contract_address)
            b.assert_(codesize)

        b.jmp(exit_bb.label)

        b.append_block(decode_bb)
        b.set_block(decode_bb)

        decoded_value = self._copy_and_decode_unbounded_external_call_return(return_t, rds)
        b.mstore(ret_cell._ptr, decoded_value.operand)
        b.jmp(exit_bb.label)

        b.append_block(exit_bb)
        b.set_block(exit_bb)

        ret_ptr = b.mload(ret_cell._ptr)
        assert isinstance(ret_ptr, IRVariable)
        return self.ctx.dynamic_memory_value(ret_ptr, return_t, annotation="external call return")

    def _unpack_dynamic_tuple_external_call_return(
        self, call_kwargs: _CallKwargs, contract_address: IROperand, return_t: TupleT
    ) -> VyperValue:
        b = self.builder
        rds = b.returndatasize()

        if call_kwargs.default_return_value is None:
            return self._copy_and_decode_dynamic_tuple_external_call_return(return_t, rds)

        ret_cell = self.ctx.allocate_buffer(32, annotation="external call dynamic tuple return ptr")
        default_bb = b.create_block("extcall_default")
        decode_bb = b.create_block("extcall_decode")
        exit_bb = b.create_block("extcall_exit")

        b.jnz(b.iszero(rds), default_bb.label, decode_bb.label)

        b.append_block(default_bb)
        b.set_block(default_bb)

        default_vv = call_kwargs.default_return_value
        assert default_vv is not None
        default_ptr = self.ctx.unwrap(default_vv)
        b.mstore(ret_cell._ptr, default_ptr)

        if not call_kwargs.skip_contract_check:
            codesize = b.extcodesize(contract_address)
            b.assert_(codesize)

        b.jmp(exit_bb.label)

        b.append_block(decode_bb)
        b.set_block(decode_bb)

        decoded_value = self._copy_and_decode_dynamic_tuple_external_call_return(return_t, rds)
        b.mstore(ret_cell._ptr, decoded_value.operand)
        b.jmp(exit_bb.label)

        b.append_block(exit_bb)
        b.set_block(exit_bb)

        ret_ptr = b.mload(ret_cell._ptr)
        assert isinstance(ret_ptr, IRVariable)
        return self.ctx.dynamic_tuple_frame_value(
            ret_ptr, return_t, annotation="external call return"
        )
