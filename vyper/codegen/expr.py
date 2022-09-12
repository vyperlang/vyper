import decimal
import math

import vyper.codegen.arithmetic as arithmetic
from vyper import ast as vy_ast
from vyper.address_space import DATA, IMMUTABLES, MEMORY, STORAGE
from vyper.codegen import external_call, self_call
from vyper.codegen.core import (
    clamp,
    ensure_in_memory,
    get_dyn_array_count,
    get_element_ptr,
    getpos,
    pop_dyn_array,
    unwrap_location,
)
from vyper.codegen.ir_node import IRnode
from vyper.codegen.keccak256_helper import keccak256_helper
from vyper.codegen.types import (
    ArrayLike,
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    DArrayType,
    EnumType,
    InterfaceType,
    MappingType,
    SArrayType,
    StringType,
    StructType,
    TupleType,
    is_base_type,
    is_bytes_m_type,
    is_numeric_type,
)
from vyper.codegen.types.convert import new_type_to_old_type
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CompilerPanic,
    EvmVersionException,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
    UnimplementedException,
    VyperException,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    SizeLimits,
    bytes_to_int,
    is_checksum_encoded,
    string_to_bytes,
    vyper_warn,
)

ENVIRONMENT_VARIABLES = {"block", "msg", "tx", "chain"}


class Expr:
    # TODO: Once other refactors are made reevaluate all inline imports

    def __init__(self, node, context):
        self.expr = node
        self.context = context

        if isinstance(node, IRnode):
            # TODO this seems bad
            self.ir_node = node
            return

        fn = getattr(self, f"parse_{type(node).__name__}", None)
        if fn is None:
            raise TypeCheckFailure(f"Invalid statement node: {type(node).__name__}")

        self.ir_node = fn()
        if self.ir_node is None:
            raise TypeCheckFailure(f"{type(node).__name__} node did not produce IR. {self.expr}")

        self.ir_node.annotation = self.expr.get("node_source_code")
        self.ir_node.source_pos = getpos(self.expr)

    def parse_Int(self):
        typ_ = self.expr._metadata.get("type")
        if typ_ is None:
            raise CompilerPanic("Type of integer literal is unknown")
        new_typ = new_type_to_old_type(typ_)
        new_typ.is_literal = True
        return IRnode.from_list(self.expr.n, typ=new_typ)

    def parse_Decimal(self):
        val = self.expr.value * DECIMAL_DIVISOR

        # sanity check that type checker did its job
        assert isinstance(val, decimal.Decimal)
        assert SizeLimits.in_bounds("decimal", val)
        assert math.ceil(val) == math.floor(val)

        val = int(val)

        return IRnode.from_list(val, typ=BaseType("decimal", is_literal=True))

    def parse_Hex(self):
        hexstr = self.expr.value

        t = self.expr._metadata.get("type")

        n_bytes = (len(hexstr) - 2) // 2  # e.g. "0x1234" is 2 bytes

        if t is not None:
            inferred_type = new_type_to_old_type(self.expr._metadata["type"])
        # This branch is a band-aid to deal with bytes20 vs address literals
        # TODO handle this properly in the type checker
        elif len(hexstr) == 42:
            inferred_type = BaseType("address", is_literal=True)
        else:
            inferred_type = BaseType(f"bytes{n_bytes}", is_literal=True)

        if is_base_type(inferred_type, "address"):
            # sanity check typechecker did its job
            assert len(hexstr) == 42 and is_checksum_encoded(hexstr)
            typ = BaseType("address")
            return IRnode.from_list(int(self.expr.value, 16), typ=typ)

        elif is_bytes_m_type(inferred_type):
            assert n_bytes == inferred_type._bytes_info.m

            # bytes_m types are left padded with zeros
            val = int(hexstr, 16) << 8 * (32 - n_bytes)

            typ = BaseType(f"bytes{n_bytes}", is_literal=True)
            return IRnode.from_list(val, typ=typ)

    # String literals
    def parse_Str(self):
        bytez, bytez_length = string_to_bytes(self.expr.value)
        typ = StringType(bytez_length, is_literal=True)
        return self._make_bytelike(typ, bytez, bytez_length)

    # Byte literals
    def parse_Bytes(self):
        bytez = self.expr.s
        bytez_length = len(self.expr.s)
        typ = ByteArrayType(bytez_length, is_literal=True)
        return self._make_bytelike(typ, bytez, bytez_length)

    def _make_bytelike(self, btype, bytez, bytez_length):
        placeholder = self.context.new_internal_variable(btype)
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
        return IRnode.from_list(
            ["seq"] + seq + [placeholder],
            typ=btype,
            location=MEMORY,
            annotation=f"Create {btype}: {bytez}",
        )

    # True, False, None constants
    def parse_NameConstant(self):
        if self.expr.value is True:
            return IRnode.from_list(1, typ=BaseType("bool", is_literal=True))
        elif self.expr.value is False:
            return IRnode.from_list(0, typ=BaseType("bool", is_literal=True))

    # Variable names
    def parse_Name(self):

        if self.expr.id == "self":
            return IRnode.from_list(["address"], typ="address")
        elif self.expr.id in self.context.vars:
            var = self.context.vars[self.expr.id]
            return IRnode.from_list(
                var.pos,
                typ=var.typ,
                location=var.location,  # either 'memory' or 'calldata' storage is handled above.
                encoding=var.encoding,
                annotation=self.expr.id,
                mutable=var.mutable,
            )

        elif self.expr._metadata["type"].is_immutable:
            var = self.context.globals[self.expr.id]
            ofst = self.expr._metadata["type"].position.offset

            if self.context.sig.is_init_func:
                mutable = True
                location = IMMUTABLES
            else:
                mutable = False
                location = DATA

            return IRnode.from_list(
                ofst, typ=var.typ, location=location, annotation=self.expr.id, mutable=mutable
            )

    # x.y or x[5]
    def parse_Attribute(self):
        typ = self.expr._metadata.get("type")
        if typ is not None:
            typ = new_type_to_old_type(typ)

        # MyEnum.foo
        if isinstance(typ, EnumType) and typ.name == self.expr.value.id:
            # 0, 1, 2, .. 255
            enum_id = typ.members[self.expr.attr]
            value = 2 ** enum_id  # 0 => 0001, 1 => 0010, 2 => 0100, etc.
            return IRnode.from_list(value, typ=typ)

        # x.balance: balance of address x
        if self.expr.attr == "balance":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if is_base_type(addr.typ, "address"):
                if (
                    isinstance(self.expr.value, vy_ast.Name)
                    and self.expr.value.id == "self"
                    and version_check(begin="istanbul")
                ):
                    seq = ["selfbalance"]
                else:
                    seq = ["balance", addr]
                return IRnode.from_list(seq, typ=BaseType("uint256"))
        # x.codesize: codesize of address x
        elif self.expr.attr == "codesize" or self.expr.attr == "is_contract":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if is_base_type(addr.typ, "address"):
                if self.expr.attr == "codesize":
                    if self.expr.get("value.id") == "self":
                        eval_code = ["codesize"]
                    else:
                        eval_code = ["extcodesize", addr]
                    output_type = "uint256"
                else:
                    eval_code = ["gt", ["extcodesize", addr], 0]
                    output_type = "bool"
                return IRnode.from_list(eval_code, typ=BaseType(output_type))
        # x.codehash: keccak of address x
        elif self.expr.attr == "codehash":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not version_check(begin="constantinople"):
                raise EvmVersionException(
                    "address.codehash is unavailable prior to constantinople ruleset", self.expr
                )
            if is_base_type(addr.typ, "address"):
                return IRnode.from_list(["extcodehash", addr], typ=BaseType("bytes32"))
        # x.code: codecopy/extcodecopy of address x
        elif self.expr.attr == "code":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if is_base_type(addr.typ, "address"):
                # These adhoc nodes will be replaced with a valid node in `Slice.build_IR`
                if addr.value == "address":  # for `self.code`
                    return IRnode.from_list(["~selfcode"], typ=ByteArrayType(0))
                return IRnode.from_list(["~extcode", addr], typ=ByteArrayType(0))
        # self.x: global attribute
        elif isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id == "self":
            type_ = self.expr._metadata["type"]
            var = self.context.globals[self.expr.attr]
            return IRnode.from_list(
                type_.position.position,
                typ=var.typ,
                location=STORAGE,
                annotation="self." + self.expr.attr,
            )
        # Reserved keywords
        elif (
            isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id in ENVIRONMENT_VARIABLES
        ):
            key = f"{self.expr.value.id}.{self.expr.attr}"
            if key == "msg.sender":
                return IRnode.from_list(["caller"], typ="address")
            elif key == "msg.data":
                # This adhoc node will be replaced with a valid node in `Slice/Len.build_IR`
                return IRnode.from_list(["~calldata"], typ=ByteArrayType(0))
            elif key == "msg.value" and self.context.is_payable:
                return IRnode.from_list(["callvalue"], typ=BaseType("uint256"))
            elif key == "msg.gas":
                return IRnode.from_list(["gas"], typ="uint256")
            elif key == "block.prevrandao":
                if not version_check(begin="paris"):
                    warning = VyperException(
                        "tried to use block.prevrandao in pre-Paris "
                        "environment! Suggest using block.difficulty instead.",
                        self.expr,
                    )
                    vyper_warn(str(warning))
                return IRnode.from_list(["prevrandao"], typ="uint256")
            elif key == "block.difficulty":
                if version_check(begin="paris"):
                    warning = VyperException(
                        "tried to use block.difficulty in post-Paris "
                        "environment! Suggest using block.prevrandao instead.",
                        self.expr,
                    )
                    vyper_warn(str(warning))
                return IRnode.from_list(["difficulty"], typ="uint256")
            elif key == "block.timestamp":
                return IRnode.from_list(["timestamp"], typ=BaseType("uint256"))
            elif key == "block.coinbase":
                return IRnode.from_list(["coinbase"], typ="address")
            elif key == "block.number":
                return IRnode.from_list(["number"], typ="uint256")
            elif key == "block.gaslimit":
                return IRnode.from_list(["gaslimit"], typ="uint256")
            elif key == "block.basefee":
                return IRnode.from_list(["basefee"], typ="uint256")
            elif key == "block.prevhash":
                return IRnode.from_list(["blockhash", ["sub", "number", 1]], typ="bytes32")
            elif key == "tx.origin":
                return IRnode.from_list(["origin"], typ="address")
            elif key == "tx.gasprice":
                return IRnode.from_list(["gasprice"], typ="uint256")
            elif key == "chain.id":
                if not version_check(begin="istanbul"):
                    raise EvmVersionException(
                        "chain.id is unavailable prior to istanbul ruleset", self.expr
                    )
                return IRnode.from_list(["chainid"], typ="uint256")
        # Other variables
        else:
            sub = Expr(self.expr.value, self.context).ir_node
            # contract type
            if isinstance(sub.typ, InterfaceType):
                return sub
            if isinstance(sub.typ, StructType) and self.expr.attr in sub.typ.members:
                return get_element_ptr(sub, self.expr.attr)

    def parse_Subscript(self):
        sub = Expr(self.expr.value, self.context).ir_node
        if sub.value == "multi":
            # force literal to memory, e.g.
            # MY_LIST: constant(decimal[6])
            # ...
            # return MY_LIST[ix]
            sub = ensure_in_memory(sub, self.context)

        if isinstance(sub.typ, MappingType):
            # TODO sanity check we are in a self.my_map[i] situation
            index = Expr.parse_value_expr(self.expr.slice.value, self.context)
            if isinstance(index.typ, ByteArrayLike):
                # we have to hash the key to get a storage location
                assert len(index.args) == 1
                index = keccak256_helper(self.expr.slice.value, index.args[0], self.context)

        elif isinstance(sub.typ, ArrayLike):
            index = Expr.parse_value_expr(self.expr.slice.value, self.context)

        elif isinstance(sub.typ, TupleType):
            index = self.expr.slice.value.n
            # note: this check should also happen in get_element_ptr
            if not 0 <= index < len(sub.typ.members):
                return
        else:
            return

        ir_node = get_element_ptr(sub, index)
        ir_node.mutable = sub.mutable
        return ir_node

    def parse_BinOp(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)

        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            return

        ltyp, rtyp = left.typ.typ, right.typ.typ

        # Sanity check - ensure that we aren't dealing with different types
        # This should be unreachable due to the type check pass
        assert ltyp == rtyp, f"unreachable, {ltyp}!={rtyp}, {self.expr}"

        if isinstance(self.expr.op, vy_ast.BitAnd):
            new_typ = left.typ
            return IRnode.from_list(["and", left, right], typ=new_typ)
        if isinstance(self.expr.op, vy_ast.BitOr):
            new_typ = left.typ
            return IRnode.from_list(["or", left, right], typ=new_typ)
        if isinstance(self.expr.op, vy_ast.BitXor):
            new_typ = left.typ
            return IRnode.from_list(["xor", left, right], typ=new_typ)

        out_typ = BaseType(ltyp)

        with left.cache_when_complex("x") as (b1, x), right.cache_when_complex("y") as (b2, y):
            if isinstance(self.expr.op, vy_ast.Add):
                ret = arithmetic.safe_add(x, y)
            elif isinstance(self.expr.op, vy_ast.Sub):
                ret = arithmetic.safe_sub(x, y)
            elif isinstance(self.expr.op, vy_ast.Mult):
                ret = arithmetic.safe_mul(x, y)
            elif isinstance(self.expr.op, vy_ast.Div):
                ret = arithmetic.safe_div(x, y)
            elif isinstance(self.expr.op, vy_ast.Mod):
                ret = arithmetic.safe_mod(x, y)
            elif isinstance(self.expr.op, vy_ast.Pow):
                ret = arithmetic.safe_pow(x, y)
            else:
                return  # raises

            return IRnode.from_list(b1.resolve(b2.resolve(ret)), typ=out_typ)

    def build_in_comparator(self):
        left = Expr(self.expr.left, self.context).ir_node
        right = Expr(self.expr.right, self.context).ir_node

        # temporary kludge to block #2637 bug
        # TODO actually fix the bug
        if not isinstance(left.typ, BaseType):
            raise TypeMismatch(
                "`in` not allowed for arrays of non-base types, tracked in issue #2637", self.expr
            )

        left = unwrap_location(left)

        if isinstance(self.expr.op, vy_ast.In):
            found, not_found = 1, 0
        elif isinstance(self.expr.op, vy_ast.NotIn):
            found, not_found = 0, 1
        else:  # pragma: no cover
            return

        i = IRnode.from_list(self.context.fresh_varname("in_ix"), typ="uint256")

        found_ptr = self.context.new_internal_variable(BaseType("bool"))

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

            if isinstance(right.typ, SArrayType):
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

            return IRnode.from_list(b1.resolve(b2.resolve(ret)), typ="bool")

    @staticmethod
    def _signed_to_unsigned_comparision_op(op):
        translation_map = {"sgt": "gt", "sge": "ge", "sle": "le", "slt": "lt"}
        if op in translation_map:
            return translation_map[op]
        else:
            return op

    def parse_Compare(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)

        if right.value is None:
            return

        if isinstance(self.expr.op, (vy_ast.In, vy_ast.NotIn)):
            if isinstance(right.typ, ArrayLike):
                return self.build_in_comparator()
            else:
                assert isinstance(right.typ, EnumType), right.typ
                intersection = ["and", left, right]
                if isinstance(self.expr.op, vy_ast.In):
                    return IRnode.from_list(["iszero", ["iszero", intersection]], typ="bool")
                elif isinstance(self.expr.op, vy_ast.NotIn):
                    return IRnode.from_list(["iszero", intersection], typ="bool")

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
        else:
            return  # pragma: notest

        # Compare (limited to 32) byte arrays.
        if isinstance(left.typ, ByteArrayLike) and isinstance(right.typ, ByteArrayLike):
            left = Expr(self.expr.left, self.context).ir_node
            right = Expr(self.expr.right, self.context).ir_node

            left_keccak = keccak256_helper(self.expr, left, self.context)
            right_keccak = keccak256_helper(self.expr, right, self.context)

            if op not in ("eq", "ne"):
                return  # raises
            else:
                # use hash even for Bytes[N<=32], because there could be dirty
                # bytes past the bytes data.
                return IRnode.from_list([op, left_keccak, right_keccak], typ="bool")

        # Compare other types.
        elif is_numeric_type(left.typ) and is_numeric_type(right.typ):
            if left.typ.typ == right.typ.typ == "uint256":
                # signed comparison ops work for any integer
                # type BESIDES uint256
                op = self._signed_to_unsigned_comparision_op(op)

        elif isinstance(left.typ, BaseType) and isinstance(right.typ, BaseType):
            if op not in ("eq", "ne"):
                return
        else:
            # kludge to block behavior in #2638
            # TODO actually implement equality for complex types
            raise TypeMismatch(
                f"operation not yet supported for {left.typ}, {right.typ}, see issue #2638",
                self.expr.op,
            )

        return IRnode.from_list([op, left, right], typ="bool")

    def parse_BoolOp(self):
        values = []
        for value in self.expr.values:
            # Check for boolean operations with non-boolean inputs
            ir_val = Expr.parse_value_expr(value, self.context)
            assert is_base_type(ir_val.typ, "bool")
            values.append(ir_val)

        assert len(values) >= 2, "bad BoolOp"

        if isinstance(self.expr.op, vy_ast.And):
            return Expr._logical_and(values)

        if isinstance(self.expr.op, vy_ast.Or):
            return Expr._logical_or(values)

        raise TypeCheckFailure(f"Unexpected boolop: {self.expr.op}")  # pragma: notest

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

        return IRnode.from_list(ir_node, typ="bool")

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

        return IRnode.from_list(ir_node, typ="bool")

    # Unary operations (only "not" supported)
    def parse_UnaryOp(self):
        operand = Expr.parse_value_expr(self.expr.operand, self.context)
        if isinstance(self.expr.op, vy_ast.Not):
            if isinstance(operand.typ, BaseType) and operand.typ.typ == "bool":
                return IRnode.from_list(["iszero", operand], typ="bool")

        if isinstance(self.expr.op, vy_ast.Invert):
            if isinstance(operand.typ, EnumType):
                n_members = len(operand.typ.members)
                # use (xor 0b11..1 operand) to flip all the bits in
                # `operand`. `mask` could be a very large constant and
                # hurt codesize, but most user enums will likely have few
                # enough members that the mask will not be large.
                mask = (2 ** n_members) - 1
                return IRnode.from_list(["xor", mask, operand], typ=operand.typ)

            if is_base_type(operand.typ, "uint256"):
                return IRnode.from_list(["not", operand], typ=operand.typ)

            # block `~` for all other integer types, since reasoning
            # about dirty bits is not entirely trivial. maybe revisit
            # this at a later date.
            raise UnimplementedException(f"~ is not supported for {operand.typ}", self.expr)

        if isinstance(self.expr.op, vy_ast.USub) and is_numeric_type(operand.typ):
            assert operand.typ._num_info.is_signed
            # Clamp on minimum signed integer value as we cannot negate that
            # value (all other integer values are fine)
            min_int_val, _ = operand.typ._num_info.bounds
            return IRnode.from_list(["sub", 0, clamp("sgt", operand, min_int_val)], typ=operand.typ)

    def _is_valid_interface_assign(self):
        if self.expr.args and len(self.expr.args) == 1:
            arg_ir = Expr(self.expr.args[0], self.context).ir_node
            if arg_ir.typ == BaseType("address"):
                return True, arg_ir
        return False, None

    # Function calls
    def parse_Call(self):
        # TODO check out this inline import
        from vyper.builtin_functions import DISPATCH_TABLE

        if isinstance(self.expr.func, vy_ast.Name):
            function_name = self.expr.func.id

            if function_name in DISPATCH_TABLE:
                return DISPATCH_TABLE[function_name].build_IR(self.expr, self.context)

            # Struct constructors do not need `self` prefix.
            elif function_name in self.context.structs:
                args = self.expr.args
                if len(args) == 1 and isinstance(args[0], vy_ast.Dict):
                    return Expr.struct_literals(args[0], function_name, self.context)

            # Interface assignment. Bar(<address>).
            elif function_name in self.context.sigs:
                ret, arg_ir = self._is_valid_interface_assign()
                if ret is True:
                    arg_ir.typ = InterfaceType(function_name)  # Cast to Correct interface type.
                    return arg_ir

        elif isinstance(self.expr.func, vy_ast.Attribute) and self.expr.func.attr == "pop":
            # TODO consider moving this to builtins
            darray = Expr(self.expr.func.value, self.context).ir_node
            assert len(self.expr.args) == 0
            assert isinstance(darray.typ, DArrayType)
            return pop_dyn_array(darray, return_popped_item=True)

        elif (
            # TODO use expr.func.type.is_internal once
            # type annotations are consistently available
            isinstance(self.expr.func, vy_ast.Attribute)
            and isinstance(self.expr.func.value, vy_ast.Name)
            and self.expr.func.value.id == "self"
        ):
            return self_call.ir_for_self_call(self.expr, self.context)
        else:
            return external_call.ir_for_external_call(self.expr, self.context)

    def parse_List(self):
        typ = new_type_to_old_type(self.expr._metadata["type"])
        if len(self.expr.elements) == 0:
            return IRnode.from_list("~empty", typ=typ)

        multi_ir = [Expr(x, self.context).ir_node for x in self.expr.elements]

        return IRnode.from_list(["multi"] + multi_ir, typ=typ)

    def parse_Tuple(self):
        tuple_elements = [Expr(x, self.context).ir_node for x in self.expr.elements]
        typ = TupleType([x.typ for x in tuple_elements], is_literal=True)
        multi_ir = IRnode.from_list(["multi"] + tuple_elements, typ=typ)
        return multi_ir

    @staticmethod
    def struct_literals(expr, name, context):
        member_subs = {}
        member_typs = {}
        for key, value in zip(expr.keys, expr.values):
            if not isinstance(key, vy_ast.Name):
                return
            if key.id in member_subs:
                return
            sub = Expr(value, context).ir_node
            member_subs[key.id] = sub
            member_typs[key.id] = sub.typ

        # TODO: get struct type from context.global_ctx.parse_type(name)
        return IRnode.from_list(
            ["multi"] + [member_subs[key] for key in member_subs.keys()],
            typ=StructType(member_typs, name, is_literal=True),
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
