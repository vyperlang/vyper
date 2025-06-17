import decimal
import math

import vyper.codegen.arithmetic as arithmetic
from vyper import ast as vy_ast
from vyper.codegen import external_call, self_call
from vyper.codegen.core import (
    append_dyn_array,
    check_assign,
    clamp,
    data_location_to_address_space,
    dummy_node_for_type,
    ensure_in_memory,
    get_dyn_array_count,
    get_element_ptr,
    is_array_like,
    is_bytes_m_type,
    is_flag_type,
    is_numeric_type,
    is_tuple_like,
    make_setter,
    pop_dyn_array,
    potential_overlap,
    read_write_overlap,
    sar,
    shl,
    shr,
    unwrap_location,
)
from vyper.codegen.ir_node import IRnode
from vyper.codegen.keccak256_helper import keccak256_helper
from vyper.evm.address_space import MEMORY
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CodegenPanic,
    CompilerPanic,
    EvmVersionException,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
    UnimplementedException,
    tag_exceptions,
)
from vyper.semantics.analysis.utils import get_expr_writes
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesT,
    DArrayT,
    DecimalT,
    FlagT,
    HashMapT,
    InterfaceT,
    ModuleT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
    is_type_t,
)
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT
from vyper.semantics.types.shortcuts import BYTES32_T, UINT256_T
from vyper.utils import DECIMAL_DIVISOR, bytes_to_int, is_checksum_encoded
from vyper.warnings import VyperWarning, vyper_warn

ENVIRONMENT_VARIABLES = {"block", "msg", "tx", "chain"}


class Expr:
    # TODO: Once other refactors are made reevaluate all inline imports

    def __init__(self, node, context, is_stmt=False):
        assert isinstance(node, vy_ast.VyperNode)
        node = node.reduced()

        self.expr = node
        self.context = context
        self.is_stmt = is_stmt  # this came from an Expr node

        fn_name = f"parse_{type(node).__name__}"
        with tag_exceptions(node, fallback_exception_type=CodegenPanic, note=fn_name):
            fn = getattr(self, fn_name)
            self.ir_node = fn()
            assert isinstance(self.ir_node, IRnode), self.ir_node

        writes = set(access.variable for access in get_expr_writes(self.expr))
        self.ir_node._writes = writes

        self.ir_node.annotation = self.expr.get("node_source_code")
        self.ir_node.ast_source = self.expr

    def parse_Int(self):
        typ = self.expr._metadata["type"]
        return IRnode.from_list(self.expr.value, typ=typ)

    def parse_Decimal(self):
        val = self.expr.value * DECIMAL_DIVISOR

        # sanity check that type checker did its job
        assert isinstance(val, decimal.Decimal)
        assert math.ceil(val) == math.floor(val)

        val = int(val)
        lo, hi = DecimalT().int_bounds
        # sanity check
        assert lo <= val <= hi

        return IRnode.from_list(val, typ=DecimalT())

    def parse_Hex(self):
        hexstr = self.expr.value

        t = self.expr._metadata["type"]

        n_bytes = (len(hexstr) - 2) // 2  # e.g. "0x1234" is 2 bytes

        if t == AddressT():
            # sanity check typechecker did its job
            assert len(hexstr) == 42 and is_checksum_encoded(hexstr)
            return IRnode.from_list(int(self.expr.value, 16), typ=t)

        elif is_bytes_m_type(t):
            assert n_bytes == t.m

            # bytes_m types are left padded with zeros
            val = int(hexstr, 16) << 8 * (32 - n_bytes)

            return IRnode.from_list(val, typ=t)

    # String literals
    def parse_Str(self):
        bytez = self.expr.value.encode("utf-8")
        return self._make_bytelike(self.context, StringT, bytez)

    # Byte literals
    def parse_Bytes(self):
        return self._make_bytelike(self.context, BytesT, self.expr.value)

    def parse_HexBytes(self):
        # HexBytes already has value as bytes
        assert isinstance(self.expr.value, bytes)
        return self._make_bytelike(self.context, BytesT, self.expr.value)

    @classmethod
    def _make_bytelike(cls, context, typeclass, bytez):
        bytez_length = len(bytez)
        btype = typeclass(bytez_length)

        placeholder = context.new_internal_variable(btype)
        seq = []
        seq.append(["mstore", placeholder, bytez_length])
        for i in range(0, len(bytez), 32):
            seq.append(
                [
                    "mstore",
                    ["add", placeholder, i + 32],
                    bytes_to_int((bytez + b"\x00" * 31)[i : i + 32]),
                ]
            )

        ret = IRnode.from_list(
            ["seq"] + seq + [placeholder],
            typ=btype,
            location=MEMORY,
            annotation=f"Create {btype}: {bytez}",
        )
        ret.is_source_bytes_literal = True
        return ret

    # True, False, None constants
    def parse_NameConstant(self):
        assert isinstance(self.expr.value, bool)
        val = int(self.expr.value)
        return IRnode.from_list(val, typ=BoolT())

    # Variable names
    def parse_Name(self):
        varname = self.expr.id

        if varname == "self":
            return IRnode.from_list(["address"], typ=AddressT())

        varinfo = self.expr._expr_info.var_info
        assert varinfo is not None

        # local variable
        if varname in self.context.vars:
            ret = self.context.lookup_var(varname).as_ir_node()
            ret._referenced_variables = {varinfo}
            return ret

        if varinfo.is_constant:
            return Expr.parse_value_expr(varinfo.decl_node.value, self.context)

        if varinfo.is_immutable:
            mutable = self.context.is_ctor_context

            location = data_location_to_address_space(
                varinfo.location, self.context.is_ctor_context
            )

            ret = IRnode.from_list(
                varinfo.position.position,
                typ=varinfo.typ,
                location=location,
                annotation=varname,
                mutable=mutable,
            )
            ret._referenced_variables = {varinfo}
            return ret

        raise CompilerPanic("unreachable")  # pragma: nocover

    # x.y or x[5]
    def parse_Attribute(self):
        typ = self.expr._metadata["type"]

        # check if we have a flag constant, e.g.
        # [lib1].MyFlag.FOO
        if isinstance(typ, FlagT) and is_type_t(self.expr.value._metadata["type"], FlagT):
            # 0, 1, 2, .. 255
            flag_id = typ._flag_members[self.expr.attr]
            value = 2**flag_id  # 0 => 0001, 1 => 0010, 2 => 0100, etc.
            return IRnode.from_list(value, typ=typ)

        # x.balance: balance of address x
        if self.expr.attr == "balance":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if addr.typ == AddressT():
                if isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id == "self":
                    seq = ["selfbalance"]
                else:
                    seq = ["balance", addr]
                return IRnode.from_list(seq, typ=UINT256_T)
        # x.codesize: codesize of address x
        elif self.expr.attr == "codesize" or self.expr.attr == "is_contract":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if addr.typ == AddressT():
                if self.expr.attr == "codesize":
                    if self.expr.get("value.id") == "self":
                        eval_code = ["codesize"]
                    else:
                        eval_code = ["extcodesize", addr]
                    output_type = UINT256_T
                else:
                    eval_code = ["gt", ["extcodesize", addr], 0]
                    output_type = BoolT()
                return IRnode.from_list(eval_code, typ=output_type)
        # x.codehash: keccak of address x
        elif self.expr.attr == "codehash":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if addr.typ == AddressT():
                return IRnode.from_list(["extcodehash", addr], typ=BYTES32_T)
        # x.code: codecopy/extcodecopy of address x
        elif self.expr.attr == "code":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if addr.typ == AddressT():
                # These adhoc nodes will be replaced with a valid node in `Slice.build_IR`
                if addr.value == "address":  # for `self.code`
                    return IRnode.from_list(["~selfcode"], typ=BytesT(0))
                return IRnode.from_list(["~extcode", addr], typ=BytesT(0))

        # Reserved keywords
        elif (
            isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id in ENVIRONMENT_VARIABLES
        ):
            key = f"{self.expr.value.id}.{self.expr.attr}"
            if key == "msg.sender":
                return IRnode.from_list(["caller"], typ=AddressT())
            elif key == "msg.data":
                # This adhoc node will be replaced with a valid node in `Slice/Len.build_IR`
                return IRnode.from_list(["~calldata"], typ=BytesT(0))
            elif key == "msg.value" and self.context.is_payable:
                return IRnode.from_list(["callvalue"], typ=UINT256_T)
            elif key in ("msg.gas", "msg.mana"):
                # NOTE: `msg.mana` is an alias for `msg.gas`
                return IRnode.from_list(["gas"], typ=UINT256_T)
            elif key == "block.prevrandao":
                if not version_check(begin="paris"):
                    warning = "tried to use block.prevrandao in pre-Paris "
                    warning += "environment! Suggest using block.difficulty instead."
                    vyper_warn(VyperWarning(warning, self.expr))
                return IRnode.from_list(["prevrandao"], typ=BYTES32_T)
            elif key == "block.difficulty":
                if version_check(begin="paris"):
                    warning = "tried to use block.difficulty in post-Paris "
                    warning += "environment! Suggest using block.prevrandao instead."
                    vyper_warn(VyperWarning(warning, self.expr))
                return IRnode.from_list(["difficulty"], typ=UINT256_T)
            elif key == "block.timestamp":
                return IRnode.from_list(["timestamp"], typ=UINT256_T)
            elif key == "block.coinbase":
                return IRnode.from_list(["coinbase"], typ=AddressT())
            elif key == "block.number":
                return IRnode.from_list(["number"], typ=UINT256_T)
            elif key == "block.gaslimit":
                return IRnode.from_list(["gaslimit"], typ=UINT256_T)
            elif key == "block.basefee":
                return IRnode.from_list(["basefee"], typ=UINT256_T)
            elif key == "block.blobbasefee":
                if not version_check(begin="cancun"):
                    raise EvmVersionException(
                        "`block.blobbasefee` is not available pre-cancun", self.expr
                    )
                return IRnode.from_list(["blobbasefee"], typ=UINT256_T)
            elif key == "block.prevhash":
                return IRnode.from_list(["blockhash", ["sub", "number", 1]], typ=BYTES32_T)
            elif key == "tx.origin":
                return IRnode.from_list(["origin"], typ=AddressT())
            elif key == "tx.gasprice":
                return IRnode.from_list(["gasprice"], typ=UINT256_T)
            elif key == "chain.id":
                return IRnode.from_list(["chainid"], typ=UINT256_T)

        # Other variables

        # self.x: global attribute
        if (varinfo := self.expr._expr_info.var_info) is not None:
            if varinfo.is_constant:
                return Expr.parse_value_expr(varinfo.decl_node.value, self.context)

            location = data_location_to_address_space(
                varinfo.location, self.context.is_ctor_context
            )

            ret = IRnode.from_list(
                varinfo.position.position,
                typ=varinfo.typ,
                location=location,
                annotation="self." + self.expr.attr,
            )
            ret._referenced_variables = {varinfo}

            return ret

        sub = Expr(self.expr.value, self.context).ir_node
        # contract type
        if isinstance(sub.typ, InterfaceT):
            # MyInterface.address
            assert self.expr.attr == "address"
            sub.typ = typ
            return sub
        if isinstance(sub.typ, StructT) and self.expr.attr in sub.typ.member_types:
            return get_element_ptr(sub, self.expr.attr)

    def parse_Subscript(self):
        sub = Expr(self.expr.value, self.context).ir_node
        if sub.value == "multi":
            # force literal to memory, e.g.
            # MY_LIST: constant(decimal[6])
            # ...
            # return MY_LIST[ix]
            sub = ensure_in_memory(sub, self.context)

        if isinstance(sub.typ, HashMapT):
            # TODO sanity check we are in a self.my_map[i] situation
            index = Expr(self.expr.slice, self.context).ir_node
            if isinstance(index.typ, _BytestringT):
                # we have to hash the key to get a storage location
                index = keccak256_helper(index, self.context)

        elif is_array_like(sub.typ):
            index = Expr.parse_value_expr(self.expr.slice, self.context)
            if read_write_overlap(sub, index):
                raise CompilerPanic("risky overlap")

        elif is_tuple_like(sub.typ):
            # should we annotate expr.slice in the frontend with the
            # folded value instead of calling reduced() here?
            index = self.expr.slice.reduced().value
            # note: this check should also happen in get_element_ptr
            if not 0 <= index < len(sub.typ.member_types):
                raise TypeCheckFailure("unreachable")
        else:
            raise TypeCheckFailure("unreachable")

        ir_node = get_element_ptr(sub, index)
        ir_node.mutable = sub.mutable
        return ir_node

    def parse_BinOp(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)

        return Expr.handle_binop(self.expr.op, left, right, self.context)

    @classmethod
    def handle_binop(cls, op, left, right, context):
        assert not left.is_pointer
        assert not right.is_pointer

        is_shift_op = isinstance(op, (vy_ast.LShift, vy_ast.RShift))

        if is_shift_op:
            assert is_numeric_type(left.typ) or is_bytes_m_type(left.typ)
            assert is_numeric_type(right.typ)
        else:
            # Sanity check - ensure that we aren't dealing with different types
            # This should be unreachable due to the type check pass
            if left.typ != right.typ:
                raise TypeCheckFailure(f"unreachable: {left.typ} != {right.typ}")
            assert is_numeric_type(left.typ) or is_flag_type(left.typ) or is_bytes_m_type(left.typ)

        out_typ = left.typ

        if isinstance(op, vy_ast.BitAnd):
            return IRnode.from_list(["and", left, right], typ=out_typ)
        if isinstance(op, vy_ast.BitOr):
            return IRnode.from_list(["or", left, right], typ=out_typ)
        if isinstance(op, vy_ast.BitXor):
            return IRnode.from_list(["xor", left, right], typ=out_typ)

        if isinstance(op, vy_ast.LShift):
            new_typ = left.typ
            if is_numeric_type(new_typ) and new_typ.bits != 256:
                # TODO implement me. ["and", 2**bits - 1, shl(right, left)]
                raise TypeCheckFailure("unreachable")
            if is_bytes_m_type(new_typ) and new_typ.m_bits != 256:
                raise TypeCheckFailure("unreachable")
            return IRnode.from_list(shl(right, left), typ=new_typ)
        if isinstance(op, vy_ast.RShift):
            new_typ = left.typ
            if is_numeric_type(new_typ) and new_typ.bits != 256:
                # TODO implement me. promote_signed_int(op(right, left), bits)
                raise TypeCheckFailure("unreachable")
            if is_bytes_m_type(new_typ) and new_typ.m_bits != 256:
                raise TypeCheckFailure("unreachable")
            op = shr if (is_bytes_m_type(left.typ) or not left.typ.is_signed) else sar
            return IRnode.from_list(op(right, left), typ=new_typ)

        # flags can only do bit ops, not arithmetic.
        assert is_numeric_type(left.typ)

        with left.cache_when_complex("x") as (b1, x), right.cache_when_complex("y") as (b2, y):
            if isinstance(op, vy_ast.Add):
                ret = arithmetic.safe_add(x, y)
            elif isinstance(op, vy_ast.Sub):
                ret = arithmetic.safe_sub(x, y)
            elif isinstance(op, vy_ast.Mult):
                ret = arithmetic.safe_mul(x, y)
            elif isinstance(op, (vy_ast.Div, vy_ast.FloorDiv)):
                ret = arithmetic.safe_div(x, y)
            elif isinstance(op, vy_ast.Mod):
                ret = arithmetic.safe_mod(x, y)
            elif isinstance(op, vy_ast.Pow):
                ret = arithmetic.safe_pow(x, y)
            else:  # pragma: nocover
                raise CompilerPanic("Unreachable")

            return IRnode.from_list(b1.resolve(b2.resolve(ret)), typ=out_typ)

    def build_in_comparator(self):
        left = Expr(self.expr.left, self.context).ir_node
        right = Expr(self.expr.right, self.context).ir_node

        # temporary kludge to block #2637 bug
        # TODO actually fix the bug
        if not left.typ._is_prim_word:
            raise TypeMismatch(
                "`in` not allowed for arrays of non-base types, tracked in issue #2637", self.expr
            )

        left = unwrap_location(left)

        if isinstance(self.expr.op, vy_ast.In):
            found, not_found = 1, 0
        elif isinstance(self.expr.op, vy_ast.NotIn):
            found, not_found = 0, 1
        else:  # pragma: no cover
            raise TypeCheckFailure("unreachable")

        i = IRnode.from_list(self.context.fresh_varname("in_ix"), typ=UINT256_T)

        found_ptr = self.context.new_internal_variable(BoolT())

        ret = ["seq"]

        with left.cache_when_complex("needle") as (b1, left), right.cache_when_complex(
            "haystack"
        ) as (b2, right):
            # unroll the loop for compile-time list literals
            if right.value == "multi":
                # empty list literals should be rejected at typechecking time
                assert len(right.args) > 0
                args = [unwrap_location(val) for val in right.args]
                if isinstance(self.expr.op, vy_ast.In):
                    checks = [["eq", left, val] for val in args]
                    return b1.resolve(b2.resolve(Expr._logical_or(checks)))
                if isinstance(self.expr.op, vy_ast.NotIn):
                    checks = [["ne", left, val] for val in args]
                    return b1.resolve(b2.resolve(Expr._logical_and(checks)))
                return  # fail

            # general case: loop over the list and check each element
            # for equality

            # location of i'th item from list
            ith_element_ptr = get_element_ptr(right, i, array_bounds_check=False)
            ith_element = unwrap_location(ith_element_ptr)

            if isinstance(right.typ, SArrayT):
                len_ = right.typ.count
            else:
                len_ = get_dyn_array_count(right)

            # Condition repeat loop has to break on.
            # TODO maybe put result on the stack
            loop_body = [
                "if",
                ["eq", left, ith_element],
                ["seq", ["mstore", found_ptr, found], "break"],  # store true.
            ]
            loop = ["repeat", i, 0, len_, right.typ.count, loop_body]

            ret.append(["seq", ["mstore", found_ptr, not_found], loop, ["mload", found_ptr]])

            return IRnode.from_list(b1.resolve(b2.resolve(ret)), typ=BoolT())

    @staticmethod
    def _signed_to_unsigned_comparison_op(op):
        translation_map = {"sgt": "gt", "sge": "ge", "sle": "le", "slt": "lt"}
        if op in translation_map:
            return translation_map[op]
        else:
            return op

    def parse_Compare(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)

        if right.value is None:
            raise TypeCheckFailure("unreachable")

        if isinstance(self.expr.op, (vy_ast.In, vy_ast.NotIn)):
            if is_array_like(right.typ):
                return self.build_in_comparator()
            else:
                assert isinstance(right.typ, FlagT), right.typ
                intersection = ["and", left, right]
                if isinstance(self.expr.op, vy_ast.In):
                    return IRnode.from_list(["iszero", ["iszero", intersection]], typ=BoolT())
                elif isinstance(self.expr.op, vy_ast.NotIn):
                    return IRnode.from_list(["iszero", intersection], typ=BoolT())

        if isinstance(self.expr.op, vy_ast.Gt):
            op = "sgt"
        elif isinstance(self.expr.op, vy_ast.GtE):
            op = "sge"
        elif isinstance(self.expr.op, vy_ast.LtE):
            op = "sle"
        elif isinstance(self.expr.op, vy_ast.Lt):
            op = "slt"
        elif isinstance(self.expr.op, vy_ast.Eq):
            op = "eq"
        elif isinstance(self.expr.op, vy_ast.NotEq):
            op = "ne"
        else:  # pragma: nocover
            return

        # Compare (limited to 32) byte arrays.
        if isinstance(left.typ, _BytestringT) and isinstance(right.typ, _BytestringT):
            left = Expr(self.expr.left, self.context).ir_node
            right = Expr(self.expr.right, self.context).ir_node

            left_keccak = keccak256_helper(left, self.context)
            right_keccak = keccak256_helper(right, self.context)

            if op not in ("eq", "ne"):
                return  # raises
            else:
                # use hash even for Bytes[N<=32], because there could be dirty
                # bytes past the bytes data.
                return IRnode.from_list([op, left_keccak, right_keccak], typ=BoolT())

        # Compare other types.
        elif is_numeric_type(left.typ) and is_numeric_type(right.typ):
            if left.typ == right.typ and right.typ == UINT256_T:
                # signed comparison ops work for any integer
                # type BESIDES uint256
                op = self._signed_to_unsigned_comparison_op(op)

        elif left.typ._is_prim_word and right.typ._is_prim_word:
            if op not in ("eq", "ne"):
                raise TypeCheckFailure("unreachable")
        else:
            # kludge to block behavior in #2638
            # TODO actually implement equality for complex types
            raise TypeMismatch(
                f"operation not yet supported for {left.typ}, {right.typ}, see issue #2638",
                self.expr.op,
            )

        return IRnode.from_list([op, left, right], typ=BoolT())

    def parse_BoolOp(self):
        values = []
        for value in self.expr.values:
            # Check for boolean operations with non-boolean inputs
            ir_val = Expr.parse_value_expr(value, self.context)
            assert ir_val.typ == BoolT()
            values.append(ir_val)

        assert len(values) >= 2, "bad BoolOp"

        if isinstance(self.expr.op, vy_ast.And):
            return Expr._logical_and(values)

        if isinstance(self.expr.op, vy_ast.Or):
            return Expr._logical_or(values)

        raise TypeCheckFailure(f"Unexpected boolop: {self.expr.op}")  # pragma: nocover

    @staticmethod
    def _logical_and(values):
        # return the logical and of a list of IRnodes

        # create a nested if statement starting from the
        # innermost node. note this also serves as the base case
        # (`_logical_and([x]) == x`)
        ir_node = values[-1]

        # iterate backward through the remaining values,
        # nesting further at each step
        for val in values[-2::-1]:
            # `x and y` => `if x { then y } { else 0 }`
            ir_node = ["if", val, ir_node, 0]

        return IRnode.from_list(ir_node, typ=BoolT())

    @staticmethod
    def _logical_or(values):
        # return the logical or of a list of IRnodes

        # create a nested if statement starting from the
        # innermost node. note this also serves as the base case
        # (`_logical_or([x]) == x`)
        ir_node = values[-1]

        # iterate backward through the remaining values,
        # nesting further at each step
        for val in values[-2::-1]:
            # `x or y` => `if x { then 1 } { else y }`
            ir_node = ["if", val, 1, ir_node]

        return IRnode.from_list(ir_node, typ=BoolT())

    # Unary operations (only "not" supported)
    def parse_UnaryOp(self):
        operand = Expr.parse_value_expr(self.expr.operand, self.context)
        if isinstance(self.expr.op, vy_ast.Not):
            if operand.typ._is_prim_word and operand.typ == BoolT():
                return IRnode.from_list(["iszero", operand], typ=BoolT())

        if isinstance(self.expr.op, vy_ast.Invert):
            if isinstance(operand.typ, FlagT):
                n_members = len(operand.typ._flag_members)
                # use (xor 0b11..1 operand) to flip all the bits in
                # `operand`. `mask` could be a very large constant and
                # hurt codesize, but most user flags will likely have few
                # enough members that the mask will not be large.
                mask = (2**n_members) - 1
                return IRnode.from_list(["xor", mask, operand], typ=operand.typ)

            if operand.typ in (UINT256_T, BYTES32_T):
                return IRnode.from_list(["not", operand], typ=operand.typ)

            # block `~` for all other types, since reasoning
            # about dirty bits is not entirely trivial. maybe revisit
            # this at a later date.
            raise UnimplementedException(f"~ is not supported for {operand.typ}", self.expr)

        if isinstance(self.expr.op, vy_ast.USub) and is_numeric_type(operand.typ):
            assert operand.typ.is_signed
            # Clamp on minimum signed integer value as we cannot negate that
            # value (all other integer values are fine)
            min_int_val, _ = operand.typ.int_bounds
            return IRnode.from_list(["sub", 0, clamp("sgt", operand, min_int_val)], typ=operand.typ)

    # Function calls
    def parse_Call(self):
        # TODO fix cyclic import
        from vyper.builtins._signatures import BuiltinFunctionT

        func = self.expr.func
        func_t = func._metadata["type"]

        if isinstance(func_t, BuiltinFunctionT):
            return func_t.build_IR(self.expr, self.context)

        # Struct constructor
        if is_type_t(func_t, StructT):
            assert not self.is_stmt  # sanity check typechecker
            return self.handle_struct_literal()

        # Interface constructor. Bar(<address>).
        if is_type_t(func_t, InterfaceT) or func.get("attr") == "__at__":
            assert not self.is_stmt  # sanity check typechecker

            # magic: do sanity checks for module.__at__
            if func.get("attr") == "__at__":
                assert isinstance(func_t, MemberFunctionT)
                assert isinstance(func.value._metadata["type"], ModuleT)

            (arg0,) = self.expr.args
            arg_ir = Expr(arg0, self.context).ir_node

            assert arg_ir.typ == AddressT()
            arg_ir.typ = self.expr._metadata["type"]

            return arg_ir

        if isinstance(func_t, MemberFunctionT):
            # TODO consider moving these to builtins or a dedicated file
            darray = Expr(func.value, self.context).ir_node
            assert isinstance(darray.typ, DArrayT)
            args = [Expr(x, self.context).ir_node for x in self.expr.args]
            if func.attr == "pop":
                darray = Expr(func.value, self.context).ir_node
                assert len(self.expr.args) == 0
                return_item = not self.is_stmt
                return pop_dyn_array(darray, return_popped_item=return_item)
            elif func.attr == "append":
                (arg,) = args
                check_assign(
                    dummy_node_for_type(darray.typ.value_type), dummy_node_for_type(arg.typ)
                )

                ret = ["seq"]
                if potential_overlap(darray, arg):
                    tmp = self.context.new_internal_variable(arg.typ)
                    ret.append(make_setter(tmp, arg))
                    arg = tmp

                ret.append(append_dyn_array(darray, arg))
                return IRnode.from_list(ret)

            raise CompilerPanic("unreachable!")  # pragma: nocover

        assert isinstance(func_t, ContractFunctionT)
        assert func_t.is_internal or func_t.is_constructor

        return self_call.ir_for_self_call(self.expr, self.context)

    @classmethod
    def handle_external_call(cls, expr, context):
        # TODO fix cyclic import
        from vyper.builtins._signatures import BuiltinFunctionT

        call_node = expr.value
        assert isinstance(call_node, vy_ast.Call)

        func_t = call_node.func._metadata["type"]

        if isinstance(func_t, BuiltinFunctionT):
            return func_t.build_IR(call_node, context)

        return external_call.ir_for_external_call(call_node, context)

    def parse_ExtCall(self):
        return self.handle_external_call(self.expr, self.context)

    def parse_StaticCall(self):
        return self.handle_external_call(self.expr, self.context)

    def parse_List(self):
        typ = self.expr._metadata["type"]
        if len(self.expr.elements) == 0:
            return IRnode.from_list("~empty", typ=typ)

        multi_ir = [Expr(x, self.context).ir_node for x in self.expr.elements]

        return IRnode.from_list(["multi"] + multi_ir, typ=typ)

    def parse_Tuple(self):
        tuple_elements = [Expr(x, self.context).ir_node for x in self.expr.elements]
        typ = TupleT([x.typ for x in tuple_elements])
        multi_ir = IRnode.from_list(["multi"] + tuple_elements, typ=typ)
        return multi_ir

    def parse_IfExp(self):
        test = Expr.parse_value_expr(self.expr.test, self.context)
        assert test.typ == BoolT()  # sanity check

        body = Expr(self.expr.body, self.context).ir_node
        orelse = Expr(self.expr.orelse, self.context).ir_node

        # if they are in the same location, we can skip copying
        # into memory. also for the case where either body or orelse are
        # literal `multi` values (ex. for tuple or arrays), copy to
        # memory (to avoid crashing in make_setter, XXX fixme).
        if body.location != orelse.location or body.value == "multi":
            body = ensure_in_memory(body, self.context)
            orelse = ensure_in_memory(orelse, self.context)

        assert body.location == orelse.location
        # check this once compare_type has no side effects:
        # assert body.typ.compare_type(orelse.typ)

        typ = self.expr._metadata["type"]
        location = body.location
        return IRnode.from_list(["if", test, body, orelse], typ=typ, location=location)

    def handle_struct_literal(self):
        expr = self.expr
        typ = expr._metadata["type"]
        member_subs = {}
        for kwarg in expr.keywords:
            assert kwarg.arg not in member_subs

            sub = Expr(kwarg.value, self.context).ir_node
            member_subs[kwarg.arg] = sub

        return IRnode.from_list(
            ["multi"] + [member_subs[key] for key in member_subs.keys()], typ=typ
        )

    # Parse an expression that results in a value
    @classmethod
    def parse_value_expr(cls, expr, context):
        return unwrap_location(cls(expr, context).ir_node)

    # Parse an expression that represents a pointer to memory/calldata or storage.
    @classmethod
    def parse_pointer_expr(cls, expr, context):
        o = cls(expr, context).ir_node
        if not o.location:
            raise StructureException("Looking for a variable location, instead got a value", expr)
        return o
