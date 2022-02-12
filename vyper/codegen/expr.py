import math
from decimal import Decimal

from vyper import ast as vy_ast
from vyper.codegen import external_call, self_call
from vyper.codegen.core import (
    clamp_basetype,
    ensure_in_memory,
    get_dyn_array_count,
    get_element_ptr,
    get_number_as_fraction,
    getpos,
    load_op,
    make_setter,
    unwrap_location,
)
from vyper.codegen.keccak256_helper import keccak256_helper
from vyper.codegen.lll_node import LLLnode
from vyper.codegen.types import (
    ArrayLike,
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    DArrayType,
    InterfaceType,
    MappingType,
    SArrayType,
    StringType,
    StructType,
    TupleType,
    is_base_type,
    is_numeric_type,
)
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CompilerPanic,
    EvmVersionException,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
)
from vyper.semantics.types import DynamicArrayDefinition
from vyper.utils import DECIMAL_DIVISOR, SizeLimits, bytes_to_int, checksum_encode, string_to_bytes

# var name: (lllnode, type)
BUILTIN_CONSTANTS = {
    "EMPTY_BYTES32": (0, "bytes32"),
    "ZERO_ADDRESS": (0, "address"),
    "MAX_INT128": (SizeLimits.MAX_INT128, "int128"),
    "MIN_INT128": (SizeLimits.MIN_INT128, "int128"),
    "MAX_INT256": (SizeLimits.MAX_INT256, "int256"),
    "MIN_INT256": (SizeLimits.MIN_INT256, "int256"),
    "MAX_DECIMAL": (SizeLimits.MAXDECIMAL, "decimal"),
    "MIN_DECIMAL": (SizeLimits.MINDECIMAL, "decimal"),
    "MAX_UINT256": (SizeLimits.MAX_UINT256, "uint256"),
}

ENVIRONMENT_VARIABLES = {
    "block",
    "msg",
    "tx",
    "chain",
}


def calculate_largest_power(a: int, num_bits: int, is_signed: bool) -> int:
    """
    For a given base `a`, compute the maximum power `b` that will not
    produce an overflow in the equation `a ** b`

    Arguments
    ---------
    a : int
        Base value for the equation `a ** b`
    num_bits : int
        The maximum number of bits that the resulting value must fit in
    is_signed : bool
        Is the operation being performed on signed integers?

    Returns
    -------
    int
        Largest possible value for `b` where the result does not overflow
        `num_bits`
    """
    if num_bits % 8:
        raise CompilerPanic("Type is not a modulo of 8")

    value_bits = num_bits - (1 if is_signed else 0)
    if a >= 2 ** value_bits:
        raise TypeCheckFailure("Value is too large and will always throw")
    elif a < -(2 ** value_bits):
        raise TypeCheckFailure("Value is too small and will always throw")

    a_is_negative = a < 0
    a = abs(a)  # No longer need to know if it's signed or not
    if a in (0, 1):
        raise CompilerPanic("Exponential operation is useless!")

    # NOTE: There is an edge case if `a` were left signed where the following
    #       operation would not work (`ln(a)` is undefined if `a <= 0`)
    b = int(Decimal(value_bits) / (Decimal(a).ln() / Decimal(2).ln()))
    if b <= 1:
        return 1  # Value is assumed to be in range, therefore power of 1 is max

    # Do a bit of iteration to ensure we have the exact number
    num_iterations = 0
    while a ** (b + 1) < 2 ** value_bits:
        b += 1
        num_iterations += 1
        assert num_iterations < 10000
    while a ** b >= 2 ** value_bits:
        b -= 1
        num_iterations += 1
        assert num_iterations < 10000

    # Edge case: If a is negative and the values of a and b are such that:
    #               (a) ** (b + 1) == -(2 ** value_bits)
    #            we can actually squeak one more out of it because it's on the edge
    if a_is_negative and (-a) ** (b + 1) == -(2 ** value_bits):  # NOTE: a = abs(a)
        return b + 1
    else:
        return b  # Exact


def calculate_largest_base(b: int, num_bits: int, is_signed: bool) -> int:
    """
    For a given power `b`, compute the maximum base `a` that will not produce an
    overflow in the equation `a ** b`

    Arguments
    ---------
    b : int
        Power value for the equation `a ** b`
    num_bits : int
        The maximum number of bits that the resulting value must fit in
    is_signed : bool
        Is the operation being performed on signed integers?

    Returns
    -------
    int
        Largest possible value for `a` where the result does not overflow
        `num_bits`
    """
    if num_bits % 8:
        raise CompilerPanic("Type is not a modulo of 8")
    if b < 0:
        raise TypeCheckFailure("Cannot calculate negative exponents")

    value_bits = num_bits - (1 if is_signed else 0)
    if b > value_bits:
        raise TypeCheckFailure("Value is too large and will always throw")
    elif b < 2:
        return 2 ** value_bits - 1  # Maximum value for type

    # Estimate (up to ~39 digits precision required)
    a = math.ceil(2 ** (Decimal(value_bits) / Decimal(b)))
    # Do a bit of iteration to ensure we have the exact number
    num_iterations = 0
    while (a + 1) ** b < 2 ** value_bits:
        a += 1
        num_iterations += 1
        assert num_iterations < 10000
    while a ** b >= 2 ** value_bits:
        a -= 1
        num_iterations += 1
        assert num_iterations < 10000

    return a


def get_min_val_for_type(typ: str) -> int:
    key = "MIN_" + typ.upper()
    try:
        min_val, _ = BUILTIN_CONSTANTS[key]
    except KeyError as e:
        raise TypeMismatch(f"Not a signed type: {typ}") from e
    return min_val


class Expr:
    # TODO: Once other refactors are made reevaluate all inline imports

    def __init__(self, node, context):
        self.expr = node
        self.context = context

        if isinstance(node, LLLnode):
            # TODO this seems bad
            self.lll_node = node
            return

        fn = getattr(self, f"parse_{type(node).__name__}", None)
        if fn is None:
            raise TypeCheckFailure(f"Invalid statement node: {type(node).__name__}")

        self.lll_node = fn()
        if self.lll_node is None:
            raise TypeCheckFailure(f"{type(node).__name__} node did not produce LLL. {self.expr}")

        self.lll_node.annotation = self.expr.get("node_source_code")

    def parse_Int(self):
        # Literal (mostly likely) becomes int256
        if self.expr.n < 0:
            return LLLnode.from_list(
                self.expr.n,
                typ=BaseType("int256", is_literal=True),
                pos=getpos(self.expr),
            )
        # Literal is large enough (mostly likely) becomes uint256.
        else:
            return LLLnode.from_list(
                self.expr.n,
                typ=BaseType("uint256", is_literal=True),
                pos=getpos(self.expr),
            )

    def parse_Decimal(self):
        numstring, num, den = get_number_as_fraction(self.expr, self.context)
        if not (SizeLimits.MIN_INT128 * den <= num <= SizeLimits.MAX_INT128 * den):
            return
        if DECIMAL_DIVISOR % den:
            return
        return LLLnode.from_list(
            num * DECIMAL_DIVISOR // den,
            typ=BaseType("decimal", is_literal=True),
            pos=getpos(self.expr),
        )

    def parse_Hex(self):
        orignum = self.expr.value
        if len(orignum) == 42 and checksum_encode(orignum) == orignum:
            return LLLnode.from_list(
                int(self.expr.value, 16),
                typ=BaseType("address", is_literal=True),
                pos=getpos(self.expr),
            )
        elif len(orignum) == 66:
            return LLLnode.from_list(
                int(self.expr.value, 16),
                typ=BaseType("bytes32", is_literal=True),
                pos=getpos(self.expr),
            )

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
        return LLLnode.from_list(
            ["seq"] + seq + [placeholder],
            typ=btype,
            location="memory",
            pos=getpos(self.expr),
            annotation=f"Create {btype}: {bytez}",
        )

    # True, False, None constants
    def parse_NameConstant(self):
        if self.expr.value is True:
            return LLLnode.from_list(
                1,
                typ=BaseType("bool", is_literal=True),
                pos=getpos(self.expr),
            )
        elif self.expr.value is False:
            return LLLnode.from_list(
                0,
                typ=BaseType("bool", is_literal=True),
                pos=getpos(self.expr),
            )

    # Variable names
    def parse_Name(self):

        if self.expr.id == "self":
            return LLLnode.from_list(["address"], typ="address", pos=getpos(self.expr))
        elif self.expr.id in self.context.vars:
            var = self.context.vars[self.expr.id]
            return LLLnode.from_list(
                var.pos,
                typ=var.typ,
                location=var.location,  # either 'memory' or 'calldata' storage is handled above.
                encoding=var.encoding,
                pos=getpos(self.expr),
                annotation=self.expr.id,
                mutable=var.mutable,
            )

        elif self.expr.id in BUILTIN_CONSTANTS:
            obj, typ = BUILTIN_CONSTANTS[self.expr.id]
            return LLLnode.from_list(
                [obj], typ=BaseType(typ, is_literal=True), pos=getpos(self.expr)
            )
        elif self.expr._metadata["type"].is_immutable:
            # immutable variable
            # need to handle constructor and outside constructor
            var = self.context.globals[self.expr.id]
            is_constructor = self.expr.get_ancestor(vy_ast.FunctionDef).get("name") == "__init__"
            if is_constructor:
                # store memory position for later access in module.py in the variable record
                memory_loc = self.context.new_variable(self.expr.id, var.typ)
                self.context.global_ctx._globals[self.expr.id].pos = memory_loc
                # store the data offset in the variable record as well for accessing
                data_offset = self.expr._metadata["type"].position.offset
                self.context.global_ctx._globals[self.expr.id].data_offset = data_offset

                return LLLnode.from_list(
                    memory_loc,
                    typ=var.typ,
                    location="memory",
                    pos=getpos(self.expr),
                    annotation=self.expr.id,
                    mutable=True,
                )
            else:
                immutable_section_size = self.context.global_ctx.immutable_section_size
                offset = self.expr._metadata["type"].position.offset
                # TODO: resolve code offsets for immutables at compile time
                return LLLnode.from_list(
                    ["sub", "codesize", immutable_section_size - offset],
                    typ=var.typ,
                    location="code",
                    pos=getpos(self.expr),
                    annotation=self.expr.id,
                    mutable=False,
                )

    # x.y or x[5]
    def parse_Attribute(self):
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
                return LLLnode.from_list(
                    seq,
                    typ=BaseType("uint256"),
                    location=None,
                    pos=getpos(self.expr),
                )
        # x.codesize: codesize of address x
        elif self.expr.attr == "codesize" or self.expr.attr == "is_contract":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if is_base_type(addr.typ, "address"):
                if self.expr.attr == "codesize":
                    if self.expr.value.id == "self":
                        eval_code = ["codesize"]
                    else:
                        eval_code = ["extcodesize", addr]
                    output_type = "uint256"
                else:
                    eval_code = ["gt", ["extcodesize", addr], 0]
                    output_type = "bool"
                return LLLnode.from_list(
                    eval_code,
                    typ=BaseType(output_type),
                    location=None,
                    pos=getpos(self.expr),
                )
        # x.codehash: keccak of address x
        elif self.expr.attr == "codehash":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not version_check(begin="constantinople"):
                raise EvmVersionException(
                    "address.codehash is unavailable prior to constantinople ruleset", self.expr
                )
            if is_base_type(addr.typ, "address"):
                return LLLnode.from_list(
                    ["extcodehash", addr],
                    typ=BaseType("bytes32"),
                    location=None,
                    pos=getpos(self.expr),
                )
        # x.code: codecopy/extcodecopy of address x
        elif self.expr.attr == "code":
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if is_base_type(addr.typ, "address"):
                # These adhoc nodes will be replaced with a valid node in `Slice.build_LLL`
                if addr.value == "address":  # for `self.code`
                    return LLLnode.from_list(["~selfcode"], typ=ByteArrayType(0))
                return LLLnode.from_list(["~extcode", addr], typ=ByteArrayType(0))
        # self.x: global attribute
        elif isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id == "self":
            type_ = self.expr._metadata["type"]
            var = self.context.globals[self.expr.attr]
            return LLLnode.from_list(
                type_.position.position,
                typ=var.typ,
                location="storage",
                pos=getpos(self.expr),
                annotation="self." + self.expr.attr,
            )
        # Reserved keywords
        elif (
            isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id in ENVIRONMENT_VARIABLES
        ):
            key = f"{self.expr.value.id}.{self.expr.attr}"
            if key == "msg.sender":
                return LLLnode.from_list(["caller"], typ="address", pos=getpos(self.expr))
            elif key == "msg.data":
                # This adhoc node will be replaced with a valid node in `Slice/Len.build_LLL`
                return LLLnode.from_list(["~calldata"], typ=ByteArrayType(0))
            elif key == "msg.value" and self.context.is_payable:
                return LLLnode.from_list(
                    ["callvalue"],
                    typ=BaseType("uint256"),
                    pos=getpos(self.expr),
                )
            elif key == "msg.gas":
                return LLLnode.from_list(
                    ["gas"],
                    typ="uint256",
                    pos=getpos(self.expr),
                )
            elif key == "block.difficulty":
                return LLLnode.from_list(
                    ["difficulty"],
                    typ="uint256",
                    pos=getpos(self.expr),
                )
            elif key == "block.timestamp":
                return LLLnode.from_list(
                    ["timestamp"],
                    typ=BaseType("uint256"),
                    pos=getpos(self.expr),
                )
            elif key == "block.coinbase":
                return LLLnode.from_list(["coinbase"], typ="address", pos=getpos(self.expr))
            elif key == "block.number":
                return LLLnode.from_list(["number"], typ="uint256", pos=getpos(self.expr))
            elif key == "block.gaslimit":
                return LLLnode.from_list(["gaslimit"], typ="uint256", pos=getpos(self.expr))
            elif key == "block.basefee":
                return LLLnode.from_list(["basefee"], typ="uint256", pos=getpos(self.expr))
            elif key == "block.prevhash":
                return LLLnode.from_list(
                    ["blockhash", ["sub", "number", 1]],
                    typ="bytes32",
                    pos=getpos(self.expr),
                )
            elif key == "tx.origin":
                return LLLnode.from_list(["origin"], typ="address", pos=getpos(self.expr))
            elif key == "tx.gasprice":
                return LLLnode.from_list(["gasprice"], typ="uint256", pos=getpos(self.expr))
            elif key == "chain.id":
                if not version_check(begin="istanbul"):
                    raise EvmVersionException(
                        "chain.id is unavailable prior to istanbul ruleset", self.expr
                    )
                return LLLnode.from_list(["chainid"], typ="uint256", pos=getpos(self.expr))
        # Other variables
        else:
            sub = Expr.parse_variable_location(self.expr.value, self.context)
            # contract type
            if isinstance(sub.typ, InterfaceType):
                return sub
            if isinstance(sub.typ, StructType) and self.expr.attr in sub.typ.members:
                return get_element_ptr(sub, self.expr.attr, pos=getpos(self.expr))

    def parse_Subscript(self):
        sub = Expr(self.expr.value, self.context).lll_node
        if sub.value == "multi":
            # force literal to memory, e.g.
            # MY_LIST: constant(decimal[6])
            # ...
            # return MY_LIST[ix]
            sub = ensure_in_memory(sub, self.context, pos=getpos(self.expr))

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

        lll_node = get_element_ptr(sub, index, pos=getpos(self.expr))
        lll_node.mutable = sub.mutable
        return lll_node

    def parse_BinOp(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)

        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            return

        pos = getpos(self.expr)
        types = {left.typ.typ, right.typ.typ}
        literals = {left.typ.is_literal, right.typ.is_literal}

        # If one value of the operation is a literal, we recast it to match the non-literal type.
        # We know this is OK because types were already verified in the actual typechecking pass.
        # This is a temporary solution to not break codegen while we work toward removing types
        # altogether at this stage of complition. @iamdefinitelyahuman
        if literals == {True, False} and len(types) > 1 and "decimal" not in types:
            if left.typ.is_literal and SizeLimits.in_bounds(right.typ.typ, left.value):
                left = LLLnode.from_list(
                    left.value,
                    typ=BaseType(right.typ.typ, is_literal=True),
                    pos=pos,
                )
            elif right.typ.is_literal and SizeLimits.in_bounds(left.typ.typ, right.value):
                right = LLLnode.from_list(
                    right.value,
                    typ=BaseType(left.typ.typ, is_literal=True),
                    pos=pos,
                )

        ltyp, rtyp = left.typ.typ, right.typ.typ
        if ltyp != rtyp:
            # Sanity check - ensure that we aren't dealing with different types
            # This should be unreachable due to the type check pass
            return

        arith = None
        if isinstance(self.expr.op, (vy_ast.Add, vy_ast.Sub)):
            new_typ = BaseType(ltyp)

            if ltyp == "uint256":
                if isinstance(self.expr.op, vy_ast.Add):
                    # safeadd
                    arith = ["seq", ["assert", ["ge", ["add", "l", "r"], "l"]], ["add", "l", "r"]]

                elif isinstance(self.expr.op, vy_ast.Sub):
                    # safesub
                    arith = ["seq", ["assert", ["ge", "l", "r"]], ["sub", "l", "r"]]

            elif ltyp == "int256":
                if isinstance(self.expr.op, vy_ast.Add):
                    op, comp1, comp2 = "add", "sge", "slt"
                else:
                    op, comp1, comp2 = "sub", "sle", "sgt"

                if right.typ.is_literal:
                    if right.value >= 0:
                        arith = ["seq", ["assert", [comp1, [op, "l", "r"], "l"]], [op, "l", "r"]]
                    else:
                        arith = ["seq", ["assert", [comp2, [op, "l", "r"], "l"]], [op, "l", "r"]]
                else:
                    arith = [
                        "with",
                        "ans",
                        [op, "l", "r"],
                        [
                            "seq",
                            [
                                "assert",
                                [
                                    "or",
                                    ["and", ["sge", "r", 0], [comp1, "ans", "l"]],
                                    ["and", ["slt", "r", 0], [comp2, "ans", "l"]],
                                ],
                            ],
                            "ans",
                        ],
                    ]

            elif ltyp in ("decimal", "int128", "uint8"):
                op = "add" if isinstance(self.expr.op, vy_ast.Add) else "sub"
                arith = [op, "l", "r"]

        elif isinstance(self.expr.op, vy_ast.Mult):
            new_typ = BaseType(ltyp)
            if ltyp == "uint256":
                arith = [
                    "with",
                    "ans",
                    ["mul", "l", "r"],
                    [
                        "seq",
                        ["assert", ["or", ["eq", ["div", "ans", "l"], "r"], ["iszero", "l"]]],
                        "ans",
                    ],
                ]

            elif ltyp == "int256":
                if version_check(begin="constantinople"):
                    upper_bound = ["shl", 255, 1]
                else:
                    upper_bound = -(2 ** 255)
                if not left.typ.is_literal and not right.typ.is_literal:
                    bounds_check = [
                        "assert",
                        ["or", ["ne", "l", ["not", 0]], ["ne", "r", upper_bound]],
                    ]
                elif left.typ.is_literal and left.value == -1:
                    bounds_check = ["assert", ["ne", "r", upper_bound]]
                elif right.typ.is_literal and right.value == -(2 ** 255):
                    bounds_check = ["assert", ["ne", "l", ["not", 0]]]
                else:
                    bounds_check = "pass"
                arith = [
                    "with",
                    "ans",
                    ["mul", "l", "r"],
                    [
                        "seq",
                        bounds_check,
                        ["assert", ["or", ["eq", ["sdiv", "ans", "l"], "r"], ["iszero", "l"]]],
                        "ans",
                    ],
                ]

            elif ltyp in ("int128", "uint8"):
                arith = ["mul", "l", "r"]

            elif ltyp == "decimal":
                arith = [
                    "with",
                    "ans",
                    ["mul", "l", "r"],
                    [
                        "seq",
                        ["assert", ["or", ["eq", ["sdiv", "ans", "l"], "r"], ["iszero", "l"]]],
                        ["sdiv", "ans", DECIMAL_DIVISOR],
                    ],
                ]

        elif isinstance(self.expr.op, vy_ast.Div):
            if right.typ.is_literal and right.value == 0:
                return

            new_typ = BaseType(ltyp)

            if right.typ.is_literal:
                divisor = "r"
            else:
                # only apply the non-zero clamp when r is not a constant
                divisor = ["clamp_nonzero", "r"]

            if ltyp in ("uint8", "uint256"):
                arith = ["div", "l", divisor]

            elif ltyp == "int256":
                if version_check(begin="constantinople"):
                    upper_bound = ["shl", 255, 1]
                else:
                    upper_bound = -(2 ** 255)
                if not left.typ.is_literal and not right.typ.is_literal:
                    bounds_check = [
                        "assert",
                        ["or", ["ne", "r", ["not", 0]], ["ne", "l", upper_bound]],
                    ]
                elif left.typ.is_literal and left.value == -(2 ** 255):
                    bounds_check = ["assert", ["ne", "r", ["not", 0]]]
                elif right.typ.is_literal and right.value == -1:
                    bounds_check = ["assert", ["ne", "l", upper_bound]]
                else:
                    bounds_check = "pass"
                arith = ["seq", bounds_check, ["sdiv", "l", divisor]]

            elif ltyp == "int128":
                arith = ["sdiv", "l", divisor]

            elif ltyp == "decimal":
                arith = [
                    "sdiv",
                    ["mul", "l", DECIMAL_DIVISOR],
                    divisor,
                ]

        elif isinstance(self.expr.op, vy_ast.Mod):
            if right.typ.is_literal and right.value == 0:
                return

            new_typ = BaseType(ltyp)

            if right.typ.is_literal:
                divisor = "r"
            else:
                # only apply the non-zero clamp when r is not a constant
                divisor = ["clamp_nonzero", "r"]

            if ltyp in ("uint8", "uint256"):
                arith = ["mod", "l", divisor]
            else:
                arith = ["smod", "l", divisor]

        elif isinstance(self.expr.op, vy_ast.Pow):
            new_typ = BaseType(ltyp)

            if self.expr.left.get("value") == 1:
                return LLLnode.from_list([1], typ=new_typ, pos=pos)
            if self.expr.left.get("value") == 0:
                return LLLnode.from_list(["iszero", right], typ=new_typ, pos=pos)

            if ltyp == "int128":
                is_signed = True
                num_bits = 128
            elif ltyp == "int256":
                is_signed = True
                num_bits = 256
            elif ltyp == "uint8":
                is_signed = False
                num_bits = 8
            else:
                is_signed = False
                num_bits = 256

            if isinstance(self.expr.left, vy_ast.Int):
                value = self.expr.left.value
                upper_bound = calculate_largest_power(value, num_bits, is_signed) + 1
                # for signed integers, this also prevents negative values
                clamp = ["lt", right, upper_bound]
                return LLLnode.from_list(
                    ["seq", ["assert", clamp], ["exp", left, right]],
                    typ=new_typ,
                    pos=pos,
                )
            elif isinstance(self.expr.right, vy_ast.Int):
                value = self.expr.right.value
                upper_bound = calculate_largest_base(value, num_bits, is_signed) + 1
                if is_signed:
                    clamp = ["and", ["slt", left, upper_bound], ["sgt", left, -upper_bound]]
                else:
                    clamp = ["lt", left, upper_bound]
                return LLLnode.from_list(
                    ["seq", ["assert", clamp], ["exp", left, right]],
                    typ=new_typ,
                    pos=pos,
                )
            else:
                # `a ** b` where neither `a` or `b` are known
                # TODO this is currently unreachable, once we implement a way to do it safely
                # remove the check in `vyper/context/types/value/numeric.py`
                return

        if arith is None:
            return

        arith = LLLnode.from_list(arith, typ=new_typ)

        p = [
            "with",
            "l",
            left,
            [
                "with",
                "r",
                right,
                # note clamp_basetype is a noop on [u]int256
                # note: clamp_basetype throws on unclampable input
                clamp_basetype(arith),
            ],
        ]
        return LLLnode.from_list(p, typ=new_typ, pos=pos)

    def build_in_comparator(self):
        left = Expr(self.expr.left, self.context).lll_node
        right = Expr(self.expr.right, self.context).lll_node

        # temporary kludge to block #2637 bug
        # TODO actually fix the bug
        if not isinstance(left.typ, BaseType):
            raise TypeMismatch(
                "`in` not allowed for arrays of non-base types, tracked in issue #2637", self.expr
            )

        if isinstance(self.expr.op, vy_ast.In):
            found, not_found = 1, 0
        elif isinstance(self.expr.op, vy_ast.NotIn):
            found, not_found = 0, 1
        else:
            return  # pragma: notest

        i = LLLnode.from_list(self.context.fresh_varname("in_ix"), typ="uint256")

        found_ptr = self.context.new_internal_variable(BaseType("bool"))

        ret = ["seq"]

        left = unwrap_location(left)
        with left.cache_when_complex("needle") as (b1, left), right.cache_when_complex(
            "haystack"
        ) as (b2, right):
            if right.value == "multi":
                # Copy literal to memory to be compared.
                tmp_list = LLLnode.from_list(
                    self.context.new_internal_variable(right.typ),
                    typ=right.typ,
                    location="memory",
                )
                ret.append(make_setter(tmp_list, right, pos=getpos(self.expr)))

                right = tmp_list

            # location of i'th item from list
            pos = getpos(self.expr)
            ith_element_ptr = get_element_ptr(right, i, array_bounds_check=False, pos=pos)
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

            ret.append(
                [
                    "seq",
                    ["mstore", found_ptr, not_found],
                    loop,
                    ["mload", found_ptr],
                ]
            )

            return LLLnode.from_list(b1.resolve(b2.resolve(ret)), typ="bool")

    @staticmethod
    def _signed_to_unsigned_comparision_op(op):
        translation_map = {
            "sgt": "gt",
            "sge": "ge",
            "sle": "le",
            "slt": "lt",
        }
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
            return  # pragma: notest

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
            left = Expr(self.expr.left, self.context).lll_node
            right = Expr(self.expr.right, self.context).lll_node

            length_mismatch = left.typ.maxlen != right.typ.maxlen
            left_over_32 = left.typ.maxlen > 32
            right_over_32 = right.typ.maxlen > 32

            if length_mismatch or left_over_32 or right_over_32:
                left_keccak = keccak256_helper(self.expr, left, self.context)
                right_keccak = keccak256_helper(self.expr, right, self.context)

                if op == "eq" or op == "ne":
                    return LLLnode.from_list(
                        [op, left_keccak, right_keccak],
                        typ="bool",
                        pos=getpos(self.expr),
                    )

                else:
                    return

            else:

                def load_bytearray(side):
                    if side.location == "storage":
                        return ["sload", ["add", 1, side]]
                    else:
                        load = load_op(side.location)
                        return [load, ["add", 32, side]]

                return LLLnode.from_list(
                    [op, load_bytearray(left), load_bytearray(right)],
                    typ="bool",
                    pos=getpos(self.expr),
                )

        # Compare other types.
        elif is_numeric_type(left.typ) and is_numeric_type(right.typ):
            if left.typ.typ == right.typ.typ == "uint256":
                # this works because we only have one unsigned integer type
                # in the future if others are added, this logic must be expanded
                op = self._signed_to_unsigned_comparision_op(op)

        elif isinstance(left.typ, BaseType) and isinstance(right.typ, BaseType):
            if op not in ("eq", "ne"):
                return
        else:
            # kludge to block behavior in #2638
            # TODO actually implement equality for complex types
            raise TypeMismatch(
                "equality not yet supported for complex types, see issue #2638", self.expr
            )

        return LLLnode.from_list([op, left, right], typ="bool", pos=getpos(self.expr))

    def parse_BoolOp(self):
        for value in self.expr.values:
            # Check for boolean operations with non-boolean inputs
            _expr = Expr.parse_value_expr(value, self.context)
            if not is_base_type(_expr.typ, "bool"):
                return

        def _build_if_lll(condition, true, false):
            # generate a basic if statement in LLL
            o = ["if", condition, true, false]
            return o

        if isinstance(self.expr.op, vy_ast.And):
            # create the initial `x and y` from the final two values
            lll_node = _build_if_lll(
                Expr.parse_value_expr(self.expr.values[-2], self.context),
                Expr.parse_value_expr(self.expr.values[-1], self.context),
                [0],
            )
            # iterate backward through the remaining values
            for node in self.expr.values[-3::-1]:
                lll_node = _build_if_lll(Expr.parse_value_expr(node, self.context), lll_node, [0])

        elif isinstance(self.expr.op, vy_ast.Or):
            # create the initial `x or y` from the final two values
            lll_node = _build_if_lll(
                Expr.parse_value_expr(self.expr.values[-2], self.context),
                [1],
                Expr.parse_value_expr(self.expr.values[-1], self.context),
            )

            # iterate backward through the remaining values
            for node in self.expr.values[-3::-1]:
                lll_node = _build_if_lll(Expr.parse_value_expr(node, self.context), 1, lll_node)
        else:
            raise TypeCheckFailure(f"Unexpected boolean operator: {type(self.expr.op).__name__}")

        return LLLnode.from_list(lll_node, typ="bool")

    # Unary operations (only "not" supported)
    def parse_UnaryOp(self):
        operand = Expr.parse_value_expr(self.expr.operand, self.context)
        if isinstance(self.expr.op, vy_ast.Not):
            if isinstance(operand.typ, BaseType) and operand.typ.typ == "bool":
                return LLLnode.from_list(["iszero", operand], typ="bool", pos=getpos(self.expr))
        elif isinstance(self.expr.op, vy_ast.USub) and is_numeric_type(operand.typ):
            # Clamp on minimum integer value as we cannot negate that value
            # (all other integer values are fine)
            min_int_val = get_min_val_for_type(operand.typ.typ)
            return LLLnode.from_list(
                ["sub", 0, ["clampgt", operand, min_int_val]],
                typ=operand.typ,
                pos=getpos(self.expr),
            )

    def _is_valid_interface_assign(self):
        if self.expr.args and len(self.expr.args) == 1:
            arg_lll = Expr(self.expr.args[0], self.context).lll_node
            if arg_lll.typ == BaseType("address"):
                return True, arg_lll
        return False, None

    # Function calls
    def parse_Call(self):
        # TODO check out this inline import
        from vyper.builtin_functions import DISPATCH_TABLE

        if isinstance(self.expr.func, vy_ast.Name):
            function_name = self.expr.func.id

            if function_name in DISPATCH_TABLE:
                return DISPATCH_TABLE[function_name].build_LLL(self.expr, self.context)

            # Struct constructors do not need `self` prefix.
            elif function_name in self.context.structs:
                args = self.expr.args
                if len(args) == 1 and isinstance(args[0], vy_ast.Dict):
                    return Expr.struct_literals(args[0], function_name, self.context)

            # Interface assignment. Bar(<address>).
            elif function_name in self.context.sigs:
                ret, arg_lll = self._is_valid_interface_assign()
                if ret is True:
                    arg_lll.typ = InterfaceType(function_name)  # Cast to Correct interface type.
                    return arg_lll
        elif (
            isinstance(self.expr.func, vy_ast.Attribute)
            and isinstance(self.expr.func.value, vy_ast.Name)
            and self.expr.func.value.id == "self"
        ):  # noqa: E501
            return self_call.lll_for_self_call(self.expr, self.context)
        else:
            return external_call.lll_for_external_call(self.expr, self.context)

    def parse_List(self):
        multi_lll = [Expr(x, self.context).lll_node for x in self.expr.elements]

        # TODO this type inference for out_type is wrong. instead should
        # use self.expr._metadata["type"]
        out_type = next((i.typ for i in multi_lll if not i.typ.is_literal), multi_lll[0].typ)
        if isinstance(self.expr._metadata["type"], DynamicArrayDefinition):
            typ = DArrayType(out_type, len(self.expr.elements), is_literal=True)
        else:
            typ = SArrayType(out_type, len(self.expr.elements), is_literal=True)

        return LLLnode.from_list(["multi"] + multi_lll, typ=typ, pos=getpos(self.expr))

    def parse_Tuple(self):
        tuple_elements = [Expr(x, self.context).lll_node for x in self.expr.elements]
        typ = TupleType([x.typ for x in tuple_elements], is_literal=True)
        multi_lll = LLLnode.from_list(["multi"] + tuple_elements, typ=typ, pos=getpos(self.expr))
        return multi_lll

    @staticmethod
    def struct_literals(expr, name, context):
        member_subs = {}
        member_typs = {}
        for key, value in zip(expr.keys, expr.values):
            if not isinstance(key, vy_ast.Name):
                return
            if key.id in member_subs:
                return
            sub = Expr(value, context).lll_node
            member_subs[key.id] = sub
            member_typs[key.id] = sub.typ
        return LLLnode.from_list(
            ["multi"] + [member_subs[key] for key in member_subs.keys()],
            typ=StructType(member_typs, name, is_literal=True),
            pos=getpos(expr),
        )

    # Parse an expression that results in a value
    @classmethod
    def parse_value_expr(cls, expr, context):
        return unwrap_location(cls(expr, context).lll_node)

    # Parse an expression that represents an address in memory/calldata or storage.
    @classmethod
    def parse_variable_location(cls, expr, context):
        o = cls(expr, context).lll_node
        if not o.location:
            raise StructureException("Looking for a variable location, instead got a value", expr)
        return o
