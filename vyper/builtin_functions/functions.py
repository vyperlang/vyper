import hashlib
import math
import operator
from decimal import Decimal

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Tuple
from vyper.address_space import MEMORY, STORAGE
from vyper.ast.signatures.function_signature import VariableRecord
from vyper.ast.validation import validate_call_args
from vyper.builtin_functions.convert import convert
from vyper.codegen.abi_encoder import abi_encode
from vyper.codegen.context import Context
from vyper.codegen.core import (
    STORE,
    IRnode,
    _freshname,
    add_ofst,
    bytes_data_ptr,
    calculate_type_for_external_return,
    check_external_call,
    clamp,
    clamp2,
    clamp_basetype,
    clamp_nonzero,
    copy_bytes,
    ensure_in_memory,
    eval_once_check,
    eval_seq,
    get_bytearray_length,
    get_element_ptr,
    ir_tuple_from_args,
    needs_external_call_wrap,
    promote_signed_int,
    sar,
    shl,
    shr,
    unwrap_location,
)
from vyper.codegen.expr import Expr
from vyper.codegen.ir_node import Encoding
from vyper.codegen.keccak256_helper import keccak256_helper
from vyper.codegen.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    SArrayType,
    StringType,
    TupleType,
    get_type_for_exact_size,
    is_base_type,
    parse_decimal_info,
    parse_integer_typeinfo,
)
from vyper.codegen.types.convert import new_type_to_old_type
from vyper.exceptions import (
    ArgumentException,
    CompilerPanic,
    InvalidLiteral,
    InvalidType,
    OverflowException,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
    UnfoldableNode,
    ZeroDivisionException,
)
from vyper.semantics.types import (
    ArrayDefinition,
    BoolDefinition,
    DynamicArrayDefinition,
    DynamicArrayPrimitive,
    TupleDefinition,
)
from vyper.semantics.types.abstract import (
    ArrayValueAbstractType,
    BytesAbstractType,
    FixedAbstractType,
    IntegerAbstractType,
    NumericAbstractType,
    SignedIntegerAbstractType,
    UnsignedIntegerAbstractType,
)
from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.utils import KwargSettings, TypeTypeDefinition, get_type_from_annotation
from vyper.semantics.types.value.address import AddressDefinition
from vyper.semantics.types.value.array_value import (
    BytesArrayDefinition,
    BytesArrayPrimitive,
    StringDefinition,
    StringPrimitive,
)
from vyper.semantics.types.value.bytes_fixed import Bytes4Definition  # type: ignore
from vyper.semantics.types.value.bytes_fixed import Bytes32Definition
from vyper.semantics.types.value.numeric import Int256Definition  # type: ignore
from vyper.semantics.types.value.numeric import Uint8Definition  # type: ignore
from vyper.semantics.types.value.numeric import Uint256Definition  # type: ignore
from vyper.semantics.types.value.numeric import DecimalDefinition
from vyper.semantics.validation.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_possible_types_from_node,
    validate_expected_type,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    EIP_170_LIMIT,
    SHA3_PER_WORD,
    MemoryPositions,
    SizeLimits,
    abi_method_id,
    bytes_to_int,
    ceil32,
    fourbytes_to_int,
    keccak256,
    vyper_warn,
)

from .signatures import BuiltinFunction, process_inputs

SHA256_ADDRESS = 2
SHA256_BASE_GAS = 60
SHA256_PER_WORD_GAS = 12


class FoldedFunction(BuiltinFunction):
    # Base class for nodes which should always be folded

    # Since foldable builtin functions are not folded before semantics validation,
    # this flag is used for `check_kwargable` in semantics validation.
    _kwargable = True


class TypenameFoldedFunction(FoldedFunction):
    # Base class for builtin functions that:
    # (1) take a typename as the only argument; and
    # (2) should always be folded.

    # "TYPE_DEFINITION" is a placeholder value for a type definition string, and
    # will be replaced by a `TypeTypeDefinition` object in `infer_arg_types`.
    _inputs = [("typename", "TYPE_DEFINITION")]

    def fetch_call_return(self, node):
        type_ = self.infer_arg_types(node)[0].typedef
        return type_

    def infer_arg_types(self, node):
        validate_call_args(node, 1)
        input_typedef = TypeTypeDefinition(
            get_type_from_annotation(node.args[0], DataLocation.MEMORY)
        )
        return [input_typedef]


class Floor(BuiltinFunction):

    _id = "floor"
    _inputs = [("value", DecimalDefinition())]
    # TODO: maybe use int136?
    _return_type = Int256Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Decimal):
            raise UnfoldableNode

        value = math.floor(node.args[0].value)
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(
            [
                "if",
                ["slt", args[0], 0],
                ["sdiv", ["sub", args[0], DECIMAL_DIVISOR - 1], DECIMAL_DIVISOR],
                ["sdiv", args[0], DECIMAL_DIVISOR],
            ],
            typ=BaseType("int256"),
        )


class Ceil(BuiltinFunction):

    _id = "ceil"
    _inputs = [("value", DecimalDefinition())]
    # TODO: maybe use int136?
    _return_type = Int256Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Decimal):
            raise UnfoldableNode

        value = math.ceil(node.args[0].value)
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(
            [
                "if",
                ["slt", args[0], 0],
                ["sdiv", args[0], DECIMAL_DIVISOR],
                ["sdiv", ["add", args[0], DECIMAL_DIVISOR - 1], DECIMAL_DIVISOR],
            ],
            typ=BaseType("int256"),
        )


class Convert(BuiltinFunction):

    _id = "convert"

    def fetch_call_return(self, node):
        _, target_typedef = self.infer_arg_types(node)

        # note: more type conversion validation happens in convert.py
        return target_typedef.typedef

    # TODO: push this down into convert.py for more consistency
    def infer_arg_types(self, node):
        validate_call_args(node, 2)

        target_type = get_type_from_annotation(node.args[1], DataLocation.UNSET)
        value_types = get_possible_types_from_node(node.args[0])

        # For `convert` of integer literals, we need to match type inference rules in
        # convert.py codegen routines.
        # TODO: This can probably be removed once constant folding for `convert` is implemented
        if len(value_types) > 1 and all(isinstance(v, IntegerAbstractType) for v in value_types):
            # Get the smallest (and unsigned if available) type for non-integer target types
            # (note this is different from the ordering returned by `get_possible_types_from_node`)
            if not isinstance(target_type, IntegerAbstractType):
                value_types = sorted(
                    value_types, key=lambda v: (v._is_signed, v._bits), reverse=True
                )
            else:
                # filter out the target type from list of possible types
                value_types = [i for i in value_types if not target_type.compare_type(i)]

        value_type = value_types.pop()

        # block conversions between same type
        if target_type.compare_type(value_type):
            raise InvalidType(f"Value and target type are both '{target_type}'", node)

        return [value_type, TypeTypeDefinition(target_type)]

    def build_IR(self, expr, context):
        return convert(expr, context)


ADHOC_SLICE_NODE_MACROS = ["~calldata", "~selfcode", "~extcode"]


def _build_adhoc_slice_node(sub: IRnode, start: IRnode, length: IRnode, context: Context) -> IRnode:
    assert length.is_literal, "typechecker failed"

    dst_typ = ByteArrayType(maxlen=length.value)
    # allocate a buffer for the return value
    np = context.new_internal_variable(dst_typ)

    # `msg.data` by `calldatacopy`
    if sub.value == "~calldata":
        node = [
            "seq",
            ["assert", ["le", ["add", start, length], "calldatasize"]],  # runtime bounds check
            ["mstore", np, length],
            ["calldatacopy", np + 32, start, length],
            np,
        ]

    # `self.code` by `codecopy`
    elif sub.value == "~selfcode":
        node = [
            "seq",
            ["assert", ["le", ["add", start, length], "codesize"]],  # runtime bounds check
            ["mstore", np, length],
            ["codecopy", np + 32, start, length],
            np,
        ]

    # `<address>.code` by `extcodecopy`
    else:
        assert sub.value == "~extcode" and len(sub.args) == 1
        node = [
            "with",
            "_extcode_address",
            sub.args[0],
            [
                "seq",
                # runtime bounds check
                ["assert", ["le", ["add", start, length], ["extcodesize", "_extcode_address"]]],
                ["mstore", np, length],
                ["extcodecopy", "_extcode_address", np + 32, start, length],
                np,
            ],
        ]

    return IRnode.from_list(node, typ=ByteArrayType(length.value), location=MEMORY)


class Slice(BuiltinFunction):

    _id = "slice"
    _inputs = [
        ("b", (Bytes32Definition(), BytesArrayPrimitive(), StringPrimitive())),
        ("start", Uint256Definition()),
        ("length", Uint256Definition()),
    ]
    _return_type = None

    def fetch_call_return(self, node):
        arg_type, _, _ = self.infer_arg_types(node)

        if isinstance(arg_type, StringDefinition):
            return_type = StringDefinition()
        else:
            return_type = BytesArrayDefinition()

        # validate start and length are in bounds

        arg = node.args[0]
        start_expr = node.args[1]
        length_expr = node.args[2]

        # CMC 2022-03-22 NOTE slight code duplication with semantics/validation/local
        is_adhoc_slice = arg.get("attr") == "code" or (
            arg.get("value.id") == "msg" and arg.get("attr") == "data"
        )

        start_literal = start_expr.value if isinstance(start_expr, vy_ast.Int) else None
        length_literal = length_expr.value if isinstance(length_expr, vy_ast.Int) else None

        if not is_adhoc_slice:
            if length_literal is not None:
                if length_literal < 1:
                    raise ArgumentException("Length cannot be less than 1", length_expr)

                if length_literal > arg_type.length:
                    raise ArgumentException(f"slice out of bounds for {arg_type}", length_expr)

            if start_literal is not None:
                if start_literal > arg_type.length:
                    raise ArgumentException(f"slice out of bounds for {arg_type}", start_expr)
                if length_literal is not None and start_literal + length_literal > arg_type.length:
                    raise ArgumentException(f"slice out of bounds for {arg_type}", node)

        # we know the length statically
        if length_literal is not None:
            return_type.set_length(length_literal)
        else:
            return_type.set_min_length(arg_type.length)

        return return_type

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        # return a concrete type for `b`
        b_type = get_possible_types_from_node(node.args[0]).pop()
        return [b_type, self._inputs[1][1], self._inputs[2][1]]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):

        src, start, length = args

        # Handle `msg.data`, `self.code`, and `<address>.code`
        if src.value in ADHOC_SLICE_NODE_MACROS:
            return _build_adhoc_slice_node(src, start, length, context)

        is_bytes32 = is_base_type(src.typ, "bytes32")
        if src.location is None:
            # it's not a pointer; force it to be one since
            # copy_bytes works on pointers.
            assert is_bytes32, src
            src = ensure_in_memory(src, context)

        with src.cache_when_complex("src") as (b1, src), start.cache_when_complex("start") as (
            b2,
            start,
        ), length.cache_when_complex("length") as (b3, length):

            if is_bytes32:
                src_maxlen = 32
            else:
                src_maxlen = src.typ.maxlen

            dst_maxlen = length.value if length.is_literal else src_maxlen

            buflen = dst_maxlen

            # add 32 bytes to the buffer size bc word access might
            # be unaligned (see below)
            if src.location == STORAGE:
                buflen += 32

            # Get returntype string or bytes
            assert isinstance(src.typ, ByteArrayLike) or is_bytes32
            if isinstance(src.typ, StringType):
                dst_typ = StringType(maxlen=dst_maxlen)
            else:
                dst_typ = ByteArrayType(maxlen=dst_maxlen)

            # allocate a buffer for the return value
            buf = context.new_internal_variable(ByteArrayType(buflen))
            # assign it the correct return type.
            # (note mismatch between dst_maxlen and buflen)
            dst = IRnode.from_list(buf, typ=dst_typ, location=MEMORY)

            dst_data = bytes_data_ptr(dst)

            if is_bytes32:
                src_len = 32
                src_data = src
            else:
                src_len = get_bytearray_length(src)
                src_data = bytes_data_ptr(src)

            # general case. byte-for-byte copy
            if src.location == STORAGE:
                # because slice uses byte-addressing but storage
                # is word-aligned, this algorithm starts at some number
                # of bytes before the data section starts, and might copy
                # an extra word. the pseudocode is:
                #   dst_data = dst + 32
                #   copy_dst = dst_data - start % 32
                #   src_data = src + 32
                #   copy_src = src_data + (start - start % 32) / 32
                #            = src_data + (start // 32)
                #   copy_bytes(copy_dst, copy_src, length)
                #   //set length AFTER copy because the length word has been clobbered!
                #   mstore(src, length)

                # start at the first word-aligned address before `start`
                # e.g. start == byte 7 -> we start copying from byte 0
                #      start == byte 32 -> we start copying from byte 32
                copy_src = IRnode.from_list(
                    ["add", src_data, ["div", start, 32]], location=src.location
                )

                # e.g. start == byte 0 -> we copy to dst_data + 0
                #      start == byte 7 -> we copy to dst_data - 7
                #      start == byte 33 -> we copy to dst_data - 1
                copy_dst = IRnode.from_list(
                    ["sub", dst_data, ["mod", start, 32]], location=dst.location
                )

                # len + (32 if start % 32 > 0 else 0)
                copy_len = ["add", length, ["mul", 32, ["iszero", ["iszero", ["mod", start, 32]]]]]
                copy_maxlen = buflen

            else:
                # all other address spaces (mem, calldata, code) we have
                # byte-aligned access so we can just do the easy thing,
                # memcopy(dst_data, src_data + dst_data)

                copy_src = add_ofst(src_data, start)
                copy_dst = dst_data
                copy_len = length
                copy_maxlen = buflen

            do_copy = copy_bytes(copy_dst, copy_src, copy_len, copy_maxlen)

            ret = [
                "seq",
                # make sure we don't overrun the source buffer
                ["assert", ["le", ["add", start, length], src_len]],  # bounds check
                do_copy,
                ["mstore", dst, length],  # set length
                dst,  # return pointer to dst
            ]
            ret = IRnode.from_list(ret, typ=dst_typ, location=MEMORY)
            return b1.resolve(b2.resolve(b3.resolve(ret)))


class Len(BuiltinFunction):

    _id = "len"
    _inputs = [("b", (ArrayValueAbstractType(), DynamicArrayPrimitive()))]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        arg = node.args[0]
        if isinstance(arg, (vy_ast.Str, vy_ast.Bytes)):
            length = len(arg.value)
        elif isinstance(arg, vy_ast.Hex):
            # 2 characters represent 1 byte and we subtract 1 to ignore the leading `0x`
            length = len(arg.value) // 2 - 1
        else:
            raise UnfoldableNode

        return vy_ast.Int.from_node(node, value=length)

    def build_IR(self, node, context):
        arg = Expr(node.args[0], context).ir_node
        if arg.value == "~calldata":
            return IRnode.from_list(["calldatasize"], typ="uint256")
        return get_bytearray_length(arg)


class Concat(BuiltinFunction):

    _id = "concat"

    def fetch_call_return(self, node):
        arg_types = self.infer_arg_types(node)

        length = 0
        for arg_t in arg_types:
            length += arg_t.length

        if isinstance(arg_types[0], BytesAbstractType):
            return_type = BytesArrayDefinition()
        else:
            return_type = StringDefinition()
        return_type.set_length(length)
        return return_type

    def infer_arg_types(self, node):
        if len(node.args) < 2:
            raise ArgumentException("Invalid argument count: expected at least 2", node)

        if node.keywords:
            raise ArgumentException("Keyword arguments are not accepted here", node.keywords[0])

        ret = []
        prev_typeclass = None
        for arg in node.args:
            validate_expected_type(arg, (BytesAbstractType(), StringDefinition()))
            arg_t = get_possible_types_from_node(arg).pop()
            current_typeclass = "Bytes" if isinstance(arg_t, BytesAbstractType) else "String"
            if prev_typeclass and current_typeclass != prev_typeclass:
                raise TypeMismatch(
                    (
                        "Concat expects consistent use of string or bytes types, "
                        "use either string or bytes."
                    ),
                    arg,
                )
            prev_typeclass = current_typeclass
            ret.append(arg_t)

        return ret

    def build_IR(self, expr, context):
        args = [Expr(arg, context).ir_node for arg in expr.args]
        if len(args) < 2:
            raise StructureException("Concat expects at least two arguments", expr)

        # Maximum length of the output
        dst_maxlen = sum(
            [
                arg.typ.maxlen if isinstance(arg.typ, ByteArrayLike) else arg.typ._bytes_info.m
                for arg in args
            ]
        )

        if isinstance(args[0].typ, StringType):
            ret_typ = StringType(maxlen=dst_maxlen)
        else:
            ret_typ = ByteArrayType(maxlen=dst_maxlen)

        # Node representing the position of the output in memory
        dst = IRnode.from_list(
            context.new_internal_variable(ret_typ),
            typ=ret_typ,
            location=MEMORY,
            annotation="concat destination",
        )

        ret = ["seq"]
        # stack item representing our current offset in the dst buffer
        ofst = "concat_ofst"

        # TODO: optimize for the case where all lengths are statically known.
        for arg in args:

            dst_data = add_ofst(bytes_data_ptr(dst), ofst)

            if isinstance(arg.typ, ByteArrayLike):
                # Ignore empty strings
                if arg.typ.maxlen == 0:
                    continue

                with arg.cache_when_complex("arg") as (b1, arg):
                    argdata = bytes_data_ptr(arg)

                    with get_bytearray_length(arg).cache_when_complex("len") as (b2, arglen):

                        do_copy = [
                            "seq",
                            copy_bytes(dst_data, argdata, arglen, arg.typ.maxlen),
                            ["set", ofst, ["add", ofst, arglen]],
                        ]
                        ret.append(b1.resolve(b2.resolve(do_copy)))

            else:
                ret.append(STORE(dst_data, unwrap_location(arg)))
                ret.append(["set", ofst, ["add", ofst, arg.typ._bytes_info.m]])

        ret.append(STORE(dst, ofst))

        # Memory location of the output
        ret.append(dst)

        return IRnode.from_list(
            ["with", ofst, 0, ret], typ=ret_typ, location=MEMORY, annotation="concat"
        )


class Keccak256(BuiltinFunction):

    _id = "keccak256"
    _inputs = [("value", (BytesAbstractType(), StringDefinition()))]
    _return_type = Bytes32Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        if isinstance(node.args[0], vy_ast.Bytes):
            value = node.args[0].value
        elif isinstance(node.args[0], vy_ast.Str):
            value = node.args[0].value.encode()
        elif isinstance(node.args[0], vy_ast.Hex):
            length = len(node.args[0].value) // 2 - 1
            value = int(node.args[0].value, 16).to_bytes(length, "big")
        else:
            raise UnfoldableNode

        hash_ = f"0x{keccak256(value).hex()}"
        return vy_ast.Hex.from_node(node, value=hash_)

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        # return a concrete type for `value`
        value_type = get_possible_types_from_node(node.args[0]).pop()
        return [value_type]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        assert len(args) == 1
        return keccak256_helper(expr, args[0], context)


def _make_sha256_call(inp_start, inp_len, out_start, out_len):
    return [
        "assert",
        [
            "staticcall",
            ["gas"],  # gas
            SHA256_ADDRESS,  # address
            inp_start,
            inp_len,
            out_start,
            out_len,
        ],
    ]


class Sha256(BuiltinFunction):

    _id = "sha256"
    _inputs = [("value", (Bytes32Definition(), BytesArrayPrimitive(), StringPrimitive()))]
    _return_type = Bytes32Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        if isinstance(node.args[0], vy_ast.Bytes):
            value = node.args[0].value
        elif isinstance(node.args[0], vy_ast.Str):
            value = node.args[0].value.encode()
        elif isinstance(node.args[0], vy_ast.Hex):
            length = len(node.args[0].value) // 2 - 1
            value = int(node.args[0].value, 16).to_bytes(length, "big")
        else:
            raise UnfoldableNode

        hash_ = f"0x{hashlib.sha256(value).hexdigest()}"
        return vy_ast.Hex.from_node(node, value=hash_)

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        # return a concrete type for `value`
        value_type = get_possible_types_from_node(node.args[0]).pop()
        return [value_type]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        sub = args[0]
        # bytes32 input
        if is_base_type(sub.typ, "bytes32"):
            return IRnode.from_list(
                [
                    "seq",
                    ["mstore", MemoryPositions.FREE_VAR_SPACE, sub],
                    _make_sha256_call(
                        inp_start=MemoryPositions.FREE_VAR_SPACE,
                        inp_len=32,
                        out_start=MemoryPositions.FREE_VAR_SPACE,
                        out_len=32,
                    ),
                    ["mload", MemoryPositions.FREE_VAR_SPACE],  # push value onto stack
                ],
                typ=BaseType("bytes32"),
                add_gas_estimate=SHA256_BASE_GAS + 1 * SHA256_PER_WORD_GAS,
            )
        # bytearay-like input
        # special case if it's already in memory
        sub = ensure_in_memory(sub, context)

        return IRnode.from_list(
            [
                "with",
                "_sub",
                sub,
                [
                    "seq",
                    _make_sha256_call(
                        # TODO use add_ofst if sub is statically known
                        inp_start=["add", "_sub", 32],
                        inp_len=["mload", "_sub"],
                        out_start=MemoryPositions.FREE_VAR_SPACE,
                        out_len=32,
                    ),
                    ["mload", MemoryPositions.FREE_VAR_SPACE],
                ],
            ],
            typ=BaseType("bytes32"),
            add_gas_estimate=SHA256_BASE_GAS + sub.typ.maxlen * SHA256_PER_WORD_GAS,
        )


class MethodID(FoldedFunction):

    _id = "method_id"

    def evaluate(self, node):
        validate_call_args(node, 1, ["output_type"])

        args = node.args
        if not isinstance(args[0], vy_ast.Str):
            raise InvalidType("method id must be given as a literal string", args[0])
        if " " in args[0].value:
            raise InvalidLiteral("Invalid function signature - no spaces allowed.")

        return_type = self.infer_kwarg_types(node)
        value = abi_method_id(args[0].value)

        if isinstance(return_type, Bytes4Definition):
            return vy_ast.Hex.from_node(node, value=hex(value))
        else:
            return vy_ast.Bytes.from_node(node, value=value.to_bytes(4, "big"))

    def fetch_call_return(self, node):
        validate_call_args(node, 1, ["output_type"])

        type_ = self.infer_kwarg_types(node)
        return type_

    def infer_kwarg_types(self, node):
        if node.keywords:
            return_type = get_type_from_annotation(node.keywords[0].value, DataLocation.UNSET)
            if isinstance(return_type, Bytes4Definition):
                return Bytes4Definition()
            elif isinstance(return_type, BytesArrayDefinition) and return_type.length == 4:
                return BytesArrayDefinition(4)
            else:
                raise ArgumentException("output_type must be Bytes[4] or bytes4", node.keywords[0])

        # If `output_type` is not given, default to `Bytes[4]`
        return BytesArrayDefinition(4)


class ECRecover(BuiltinFunction):

    _id = "ecrecover"
    _inputs = [
        ("hash", Bytes32Definition()),
        ("v", (Uint256Definition(), Uint8Definition())),
        ("r", (Uint256Definition(), Bytes32Definition())),
        ("s", (Uint256Definition(), Bytes32Definition())),
    ]
    _return_type = AddressDefinition()

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        v_t, r_t, s_t = [get_possible_types_from_node(arg).pop() for arg in node.args[1:]]
        return [Bytes32Definition(), v_t, r_t, s_t]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        placeholder_node = IRnode.from_list(
            context.new_internal_variable(ByteArrayType(128)),
            typ=ByteArrayType(128),
            location=MEMORY,
        )
        return IRnode.from_list(
            [
                "seq",
                ["mstore", placeholder_node, args[0]],
                ["mstore", ["add", placeholder_node, 32], args[1]],
                ["mstore", ["add", placeholder_node, 64], args[2]],
                ["mstore", ["add", placeholder_node, 96], args[3]],
                [
                    "pop",
                    [
                        "staticcall",
                        ["gas"],
                        1,
                        placeholder_node,
                        128,
                        MemoryPositions.FREE_VAR_SPACE,
                        32,
                    ],
                ],
                ["mload", MemoryPositions.FREE_VAR_SPACE],
            ],
            typ=BaseType("address"),
        )


def _getelem(arg, ind):
    return unwrap_location(get_element_ptr(arg, IRnode.from_list(ind, "int128")))


class ECAdd(BuiltinFunction):

    _id = "ecadd"
    _inputs = [
        ("a", ArrayDefinition(Uint256Definition(), 2)),
        ("b", ArrayDefinition(Uint256Definition(), 2)),
    ]
    _return_type = ArrayDefinition(Uint256Definition(), 2)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        placeholder_node = IRnode.from_list(
            context.new_internal_variable(ByteArrayType(128)),
            typ=ByteArrayType(128),
            location=MEMORY,
        )
        o = IRnode.from_list(
            [
                "seq",
                ["mstore", placeholder_node, _getelem(args[0], 0)],
                ["mstore", ["add", placeholder_node, 32], _getelem(args[0], 1)],
                ["mstore", ["add", placeholder_node, 64], _getelem(args[1], 0)],
                ["mstore", ["add", placeholder_node, 96], _getelem(args[1], 1)],
                ["assert", ["staticcall", ["gas"], 6, placeholder_node, 128, placeholder_node, 64]],
                placeholder_node,
            ],
            typ=SArrayType(BaseType("uint256"), 2),
            location=MEMORY,
        )
        return o


class ECMul(BuiltinFunction):

    _id = "ecmul"
    _inputs = [("point", ArrayDefinition(Uint256Definition(), 2)), ("scalar", Uint256Definition())]
    _return_type = ArrayDefinition(Uint256Definition(), 2)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        placeholder_node = IRnode.from_list(
            context.new_internal_variable(ByteArrayType(128)),
            typ=ByteArrayType(128),
            location=MEMORY,
        )
        o = IRnode.from_list(
            [
                "seq",
                ["mstore", placeholder_node, _getelem(args[0], 0)],
                ["mstore", ["add", placeholder_node, 32], _getelem(args[0], 1)],
                ["mstore", ["add", placeholder_node, 64], args[1]],
                ["assert", ["staticcall", ["gas"], 7, placeholder_node, 96, placeholder_node, 64]],
                placeholder_node,
            ],
            typ=SArrayType(BaseType("uint256"), 2),
            location=MEMORY,
        )
        return o


def _generic_element_getter(op):
    def f(index):
        return IRnode.from_list(
            [op, ["add", "_sub", ["add", 32, ["mul", 32, index]]]], typ=BaseType("int128")
        )

    return f


def _storage_element_getter(index):
    return IRnode.from_list(["sload", ["add", "_sub", ["add", 1, index]]], typ=BaseType("int128"))


class Extract32(BuiltinFunction):

    _id = "extract32"
    _inputs = [("b", BytesArrayPrimitive()), ("start", UnsignedIntegerAbstractType())]
    # "TYPE_DEFINITION" is a placeholder value for a type definition string, and
    # will be replaced by a `TypeTypeDefinition` object in `infer_kwarg_types`
    # (note that it is ignored in `_validate_arg_types`)
    _kwargs = {"output_type": KwargSettings("TYPE_DEFINITION", "bytes32")}
    _return_type = None

    def fetch_call_return(self, node):
        self._validate_arg_types(node)
        return_type = self.infer_kwarg_types(node)["output_type"].typedef
        return return_type

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        input_type = get_possible_types_from_node(node.args[0]).pop()
        return [input_type, Uint256Definition()]

    def infer_kwarg_types(self, node):
        if node.keywords:
            output_type = get_type_from_annotation(node.keywords[0].value, DataLocation.MEMORY)
            if not isinstance(
                output_type, (AddressDefinition, Bytes32Definition, IntegerAbstractType)
            ):
                raise InvalidType(
                    "Output type must be one of integer, bytes32 or address", node.keywords[0].value
                )
            output_typedef = TypeTypeDefinition(output_type)
            node.keywords[0].value._metadata["type"] = output_typedef
        else:
            output_typedef = TypeTypeDefinition(Bytes32Definition())

        return {"output_type": output_typedef}

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        sub, index = args
        ret_type = kwargs["output_type"]

        # Get length and specific element
        if sub.location == STORAGE:
            lengetter = IRnode.from_list(["sload", "_sub"], typ=BaseType("int128"))
            elementgetter = _storage_element_getter

        else:
            op = sub.location.load_op
            lengetter = IRnode.from_list([op, "_sub"], typ=BaseType("int128"))
            elementgetter = _generic_element_getter(op)

        # TODO rewrite all this with cache_when_complex and bitshifts

        # Special case: index known to be a multiple of 32
        if isinstance(index.value, int) and not index.value % 32:
            o = IRnode.from_list(
                [
                    "with",
                    "_sub",
                    sub,
                    elementgetter(
                        ["div", clamp2(0, index, ["sub", lengetter, 32], signed=True), 32]
                    ),
                ],
                typ=ret_type,
                annotation="extracting 32 bytes",
            )
        # General case
        else:
            o = IRnode.from_list(
                [
                    "with",
                    "_sub",
                    sub,
                    [
                        "with",
                        "_len",
                        lengetter,
                        [
                            "with",
                            "_index",
                            clamp2(0, index, ["sub", "_len", 32], signed=True),
                            [
                                "with",
                                "_mi32",
                                ["mod", "_index", 32],
                                [
                                    "with",
                                    "_di32",
                                    ["div", "_index", 32],
                                    [
                                        "if",
                                        "_mi32",
                                        [
                                            "add",
                                            ["mul", elementgetter("_di32"), ["exp", 256, "_mi32"]],
                                            [
                                                "div",
                                                elementgetter(["add", "_di32", 1]),
                                                ["exp", 256, ["sub", 32, "_mi32"]],
                                            ],
                                        ],
                                        elementgetter("_di32"),
                                    ],
                                ],
                            ],
                        ],
                    ],
                ],
                typ=ret_type,
                annotation="extract32",
            )
        return IRnode.from_list(clamp_basetype(o), typ=ret_type)


class AsWeiValue(BuiltinFunction):

    _id = "as_wei_value"
    _inputs = [("value", NumericAbstractType()), ("unit", StringDefinition())]
    _return_type = Uint256Definition()

    wei_denoms = {
        ("wei",): 1,
        ("femtoether", "kwei", "babbage"): 10 ** 3,
        ("picoether", "mwei", "lovelace"): 10 ** 6,
        ("nanoether", "gwei", "shannon"): 10 ** 9,
        ("microether", "szabo"): 10 ** 12,
        ("milliether", "finney"): 10 ** 15,
        ("ether",): 10 ** 18,
        ("kether", "grand"): 10 ** 21,
    }

    def get_denomination(self, node):
        if not isinstance(node.args[1], vy_ast.Str):
            raise ArgumentException(
                "Wei denomination must be given as a literal string", node.args[1]
            )
        try:
            denom = next(v for k, v in self.wei_denoms.items() if node.args[1].value in k)
        except StopIteration:
            raise ArgumentException(
                f"Unknown denomination: {node.args[1].value}", node.args[1]
            ) from None

        return denom

    def evaluate(self, node):
        validate_call_args(node, 2)
        denom = self.get_denomination(node)

        if not isinstance(node.args[0], (vy_ast.Decimal, vy_ast.Int)):
            raise UnfoldableNode
        value = node.args[0].value

        if value < 0:
            raise InvalidLiteral("Negative wei value not allowed", node.args[0])

        if isinstance(value, int) and value >= 2 ** 256:
            raise InvalidLiteral("Value out of range for uint256", node.args[0])
        if isinstance(value, Decimal) and value >= 2 ** 127:
            raise InvalidLiteral("Value out of range for decimal", node.args[0])

        return vy_ast.Int.from_node(node, value=int(value * denom))

    def fetch_call_return(self, node):
        self.infer_arg_types(node)
        return self._return_type

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        # return a concrete type instead of NumericAbstractType
        value_type = get_possible_types_from_node(node.args[0]).pop()
        return [value_type, self._inputs[1][1]]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        value = args[0]

        denom_divisor = self.get_denomination(expr)
        if value.typ.typ == "uint256" or value.typ.typ == "uint8":
            sub = [
                "with",
                "ans",
                ["mul", value, denom_divisor],
                [
                    "seq",
                    [
                        "assert",
                        ["or", ["eq", ["div", "ans", value], denom_divisor], ["iszero", value]],
                    ],
                    "ans",
                ],
            ]
        elif value.typ.typ == "int128":
            # signed types do not require bounds checks because the
            # largest possible converted value will not overflow 2**256
            sub = ["seq", ["assert", ["sgt", value, -1]], ["mul", value, denom_divisor]]
        elif value.typ.typ == "decimal":
            sub = [
                "seq",
                ["assert", ["sgt", value, -1]],
                ["div", ["mul", value, denom_divisor], DECIMAL_DIVISOR],
            ]
        else:
            raise CompilerPanic(f"Unexpected type: {value.typ.typ}")

        return IRnode.from_list(sub, typ=BaseType("uint256"))


zero_value = IRnode.from_list(0, typ=BaseType("uint256"))
empty_value = IRnode.from_list(0, typ=BaseType("bytes32"))


class RawCall(BuiltinFunction):

    _id = "raw_call"
    _inputs = [("to", AddressDefinition()), ("data", BytesAbstractType())]
    _kwargs = {
        "max_outsize": KwargSettings(Uint256Definition(), 0, require_literal=True),
        "gas": KwargSettings(Uint256Definition(), "gas"),
        "value": KwargSettings(Uint256Definition(), zero_value),
        "is_delegate_call": KwargSettings(BoolDefinition(), False, require_literal=True),
        "is_static_call": KwargSettings(BoolDefinition(), False, require_literal=True),
        "revert_on_failure": KwargSettings(BoolDefinition(), True, require_literal=True),
    }
    _return_type = None

    def fetch_call_return(self, node):
        self._validate_arg_types(node)

        kwargz = {i.arg: i.value for i in node.keywords}

        outsize = kwargz.get("max_outsize")
        revert_on_failure = kwargz.get("revert_on_failure")
        revert_on_failure = revert_on_failure.value if revert_on_failure is not None else True

        if outsize is None:
            if revert_on_failure:
                return None
            return BoolDefinition()

        if not isinstance(outsize, vy_ast.Int) or outsize.value < 0:
            raise

        if outsize.value:
            return_type = BytesArrayDefinition()
            return_type.set_min_length(outsize.value)

            if revert_on_failure:
                return return_type
            return TupleDefinition([BoolDefinition(), return_type])

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        # return a concrete type for `data`
        data_type = get_possible_types_from_node(node.args[1]).pop()
        return [self._inputs[0][1], data_type]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        to, data = args
        # TODO: must compile in source code order, left-to-right
        gas, value, outsize, delegate_call, static_call, revert_on_failure = (
            kwargs["gas"],
            kwargs["value"],
            kwargs["max_outsize"],
            kwargs["is_delegate_call"],
            kwargs["is_static_call"],
            kwargs["revert_on_failure"],
        )

        if delegate_call and static_call:
            raise ArgumentException(
                "Call may use one of `is_delegate_call` or `is_static_call`, not both", expr
            )
        if not static_call and context.is_constant():
            raise StateAccessViolation(
                f"Cannot make modifying calls from {context.pp_constancy()},"
                " use `is_static_call=True` to perform this action",
                expr,
            )

        if data.value == "~calldata":
            call_ir = ["with", "mem_ofst", "msize"]
            args_ofst = ["seq", ["calldatacopy", "mem_ofst", 0, "calldatasize"], "mem_ofst"]
            args_len = "calldatasize"
        else:
            # some gymnastics to propagate constants (if eval_input_buf
            # returns a static memory location)
            eval_input_buf = ensure_in_memory(data, context)

            input_buf = eval_seq(eval_input_buf)

            if input_buf is None:
                call_ir = ["with", "arg_buf", eval_input_buf]
                input_buf = IRnode.from_list("arg_buf")
            else:
                call_ir = ["seq", eval_input_buf]

            args_ofst = add_ofst(input_buf, 32)
            args_len = ["mload", input_buf]

        output_node = IRnode.from_list(
            context.new_internal_variable(ByteArrayType(outsize)),
            typ=ByteArrayType(outsize),
            location=MEMORY,
        )

        bool_ty = BaseType("bool")

        # build IR for call or delegatecall
        common_call_args = [
            args_ofst,
            args_len,
            # if there is no return value, the return offset can be 0
            add_ofst(output_node, 32) if outsize else 0,
            outsize,
        ]

        if delegate_call:
            call_op = ["delegatecall", gas, to, *common_call_args]
        elif static_call:
            call_op = ["staticcall", gas, to, *common_call_args]
        else:
            call_op = ["call", gas, to, value, *common_call_args]

        call_ir += [call_op]

        # build sequence IR
        if outsize:
            # return minimum of outsize and returndatasize
            size = ["select", ["lt", outsize, "returndatasize"], outsize, "returndatasize"]

            # store output size and return output location
            store_output_size = ["seq", ["mstore", output_node, size], output_node]

            bytes_ty = ByteArrayType(outsize)

            if revert_on_failure:
                typ = bytes_ty
                ret_ir = ["seq", check_external_call(call_ir), store_output_size]
            else:
                typ = TupleType([bool_ty, bytes_ty])
                ret_ir = [
                    "multi",
                    # use IRnode.from_list to make sure the types are
                    # set properly on the "multi" members
                    IRnode.from_list(call_ir, typ=bool_ty),
                    IRnode.from_list(store_output_size, typ=bytes_ty, location=MEMORY),
                ]

        else:
            if revert_on_failure:
                typ = None
                ret_ir = check_external_call(call_ir)
            else:
                typ = bool_ty
                ret_ir = call_ir

        return IRnode.from_list(ret_ir, typ=typ, location=MEMORY)


class Send(BuiltinFunction):

    _id = "send"
    _inputs = [("to", AddressDefinition()), ("value", Uint256Definition())]
    _return_type = None

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        to, value = args
        context.check_is_not_constant("send ether", expr)
        return IRnode.from_list(["assert", ["call", 0, to, value, 0, 0, 0, 0]])


class SelfDestruct(BuiltinFunction):

    _id = "selfdestruct"
    _inputs = [("to", AddressDefinition())]
    _return_type = None
    _is_terminus = True

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        context.check_is_not_constant("selfdestruct", expr)
        return IRnode.from_list(
            ["seq", eval_once_check(_freshname("selfdestruct")), ["selfdestruct", args[0]]]
        )


class BlockHash(BuiltinFunction):

    _id = "blockhash"
    _inputs = [("block_num", Uint256Definition())]
    _return_type = Bytes32Definition()

    @process_inputs
    def build_IR(self, expr, args, kwargs, contact):
        return IRnode.from_list(
            ["blockhash", clamp("lt", clamp("sge", args[0], ["sub", ["number"], 256]), "number")],
            typ=BaseType("bytes32"),
        )


class RawLog(BuiltinFunction):

    _id = "raw_log"
    _inputs = [
        ("topics", DynamicArrayDefinition(Bytes32Definition(), 4)),
        ("data", (Bytes32Definition(), BytesArrayPrimitive())),
    ]

    def fetch_call_return(self, node):
        self.infer_arg_types(node)

    def infer_arg_types(self, node):
        self._validate_arg_types(node)

        if not isinstance(node.args[0], vy_ast.List) or len(node.args[0].elements) > 4:
            raise InvalidType("Expecting a list of 0-4 topics as first argument", node.args[0])

        # return a concrete type for `data`
        data_type = get_possible_types_from_node(node.args[1]).pop()

        return [self._inputs[0][1], data_type]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        topics_length = len(expr.args[0].elements)
        topics = args[0].args

        # sanity check topics is a literal list
        assert args[0].value in ("~empty", "multi")

        data = args[1]

        if data.typ == BaseType("bytes32"):
            placeholder = context.new_internal_variable(BaseType("bytes32"))
            return IRnode.from_list(
                [
                    "seq",
                    # TODO use make_setter
                    ["mstore", placeholder, unwrap_location(data)],
                    ["log" + str(topics_length), placeholder, 32] + topics,
                ]
            )

        input_buf = ensure_in_memory(data, context)

        return IRnode.from_list(
            [
                "with",
                "_sub",
                input_buf,
                ["log" + str(topics_length), ["add", "_sub", 32], ["mload", "_sub"], *topics],
            ]
        )


class BitwiseAnd(BuiltinFunction):

    _id = "bitwise_and"
    _inputs = [("x", Uint256Definition()), ("y", Uint256Definition())]
    _return_type = Uint256Definition()
    _warned = False

    def evaluate(self, node):
        if not self.__class__._warned:
            vyper_warn("`bitwise_and()` is deprecated! Please use the & operator instead.")
            self.__class__._warned = True

        validate_call_args(node, 2)
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = node.args[0].value & node.args[1].value
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["and", args[0], args[1]], typ=BaseType("uint256"))


class BitwiseOr(BuiltinFunction):

    _id = "bitwise_or"
    _inputs = [("x", Uint256Definition()), ("y", Uint256Definition())]
    _return_type = Uint256Definition()
    _warned = False

    def evaluate(self, node):
        if not self.__class__._warned:
            vyper_warn("`bitwise_or()` is deprecated! Please use the | operator instead.")
            self.__class__._warned = True

        validate_call_args(node, 2)
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = node.args[0].value | node.args[1].value
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["or", args[0], args[1]], typ=BaseType("uint256"))


class BitwiseXor(BuiltinFunction):

    _id = "bitwise_xor"
    _inputs = [("x", Uint256Definition()), ("y", Uint256Definition())]
    _return_type = Uint256Definition()
    _warned = False

    def evaluate(self, node):
        if not self.__class__._warned:
            vyper_warn("`bitwise_xor()` is deprecated! Please use the ^ operator instead.")
            self.__class__._warned = True

        validate_call_args(node, 2)
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = node.args[0].value ^ node.args[1].value
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["xor", args[0], args[1]], typ=BaseType("uint256"))


class BitwiseNot(BuiltinFunction):

    _id = "bitwise_not"
    _inputs = [("x", Uint256Definition())]
    _return_type = Uint256Definition()
    _warned = False

    def evaluate(self, node):
        if not self.__class__._warned:
            vyper_warn("`bitwise_not()` is deprecated! Please use the ^ operator instead.")
            self.__class__._warned = True

        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Num):
            raise UnfoldableNode

        value = node.args[0].value
        if value < 0 or value >= 2 ** 256:
            raise InvalidLiteral("Value out of range for uint256", node.args[0])

        value = (2 ** 256 - 1) - value
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["not", args[0]], typ=BaseType("uint256"))


class Shift(BuiltinFunction):

    _id = "shift"
    _inputs = [
        ("x", (Uint256Definition(), Int256Definition())),
        ("shift_bits", SignedIntegerAbstractType()),
    ]

    def evaluate(self, node):
        validate_call_args(node, 2)
        if [i for i in node.args if not isinstance(i, vy_ast.Num)]:
            raise UnfoldableNode
        value, shift = [i.value for i in node.args]
        if value < 0 or value >= 2 ** 256:
            raise InvalidLiteral("Value out of range for uint256", node.args[0])
        if shift < -(2 ** 127) or shift >= 2 ** 127:
            raise InvalidLiteral("Value out of range for int128", node.args[1])

        if shift < 0:
            value = value >> -shift
        else:
            value = (value << shift) % (2 ** 256)
        return vy_ast.Int.from_node(node, value=value)

    def fetch_call_return(self, node):
        # return type is the type of the first argument
        return self.infer_arg_types(node)[0]

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        # return a concrete type instead of SignedIntegerAbstractType
        arg_ty = get_possible_types_from_node(node.args[0])[0]
        shift_ty = get_possible_types_from_node(node.args[1])[0]
        return [arg_ty, shift_ty]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        # "gshr" -- generalized right shift
        argty = args[0].typ
        GSHR = sar if argty._int_info.is_signed else shr

        with args[0].cache_when_complex("to_shift") as (b1, arg), args[1].cache_when_complex(
            "bits"
        ) as (b2, bits):
            neg_bits = ["sub", 0, bits]
            ret = ["if", ["slt", bits, 0], GSHR(neg_bits, arg), shl(bits, arg)]
            return b1.resolve(b2.resolve(IRnode.from_list(ret, typ=argty)))


class _AddMulMod(BuiltinFunction):

    _inputs = [("a", Uint256Definition()), ("b", Uint256Definition()), ("c", Uint256Definition())]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 3)
        if isinstance(node.args[2], vy_ast.Num) and node.args[2].value == 0:
            raise ZeroDivisionException("Modulo by 0", node.args[2])
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = self._eval_fn(node.args[0].value, node.args[1].value) % node.args[2].value
        return vy_ast.Int.from_node(node, value=value)

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(
            ["seq", ["assert", args[2]], [self._opcode, args[0], args[1], args[2]]],
            typ=BaseType("uint256"),
        )


class AddMod(_AddMulMod):
    _id = "uint256_addmod"
    _eval_fn = operator.add
    _opcode = "addmod"


class MulMod(_AddMulMod):
    _id = "uint256_mulmod"
    _eval_fn = operator.mul
    _opcode = "mulmod"


class PowMod256(BuiltinFunction):
    _id = "pow_mod256"
    _inputs = [("a", Uint256Definition()), ("b", Uint256Definition())]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 2)
        if next((i for i in node.args if not isinstance(i, vy_ast.Int)), None):
            raise UnfoldableNode

        left, right = node.args
        if left.value < 0 or right.value < 0:
            raise UnfoldableNode

        value = (left.value ** right.value) % (2 ** 256)
        return vy_ast.Int.from_node(node, value=value)

    def build_IR(self, expr, context):
        left = Expr.parse_value_expr(expr.args[0], context)
        right = Expr.parse_value_expr(expr.args[1], context)
        return IRnode.from_list(["exp", left, right], typ=left.typ)


class Abs(BuiltinFunction):
    _id = "abs"
    _inputs = [("value", Int256Definition())]
    _return_type = Int256Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Int):
            raise UnfoldableNode

        value = node.args[0].value
        if not SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_INT256:
            raise OverflowException("Literal is outside of allowable range for int256")
        value = abs(value)
        if not SizeLimits.MIN_INT256 <= value <= SizeLimits.MAX_INT256:
            raise OverflowException("Absolute literal value is outside allowable range for int256")

        return vy_ast.Int.from_node(node, value=value)

    def build_IR(self, expr, context):
        value = Expr.parse_value_expr(expr.args[0], context)
        sub = [
            "with",
            "orig",
            value,
            [
                "if",
                ["slt", "orig", 0],
                # clamp orig != -2**255 (because it maps to itself under negation)
                ["seq", ["assert", ["ne", "orig", ["sub", 0, "orig"]]], ["sub", 0, "orig"]],
                "orig",
            ],
        ]
        return IRnode.from_list(sub, typ=BaseType("int256"))


# CREATE* functions

# create helper functions
# generates CREATE op sequence + zero check for result
def _create_ir(value, buf, length, salt=None, checked=True):
    args = [value, buf, length]
    create_op = "create"
    if salt is not None:
        create_op = "create2"
        args.append(salt)

    ret = IRnode.from_list(
        ["seq", eval_once_check(_freshname("create_builtin")), [create_op, *args]]
    )

    if not checked:
        return ret

    return clamp_nonzero(ret)


# calculate the gas used by create for a given number of bytes
def _create_addl_gas_estimate(size, should_use_create2):
    ret = 200 * size
    if should_use_create2:
        ret += SHA3_PER_WORD * ceil32(size) // 32
    return ret


def eip1167_bytecode():
    # NOTE cyclic import?
    from vyper.ir.compile_ir import assembly_to_evm

    loader_asm = [
        "PUSH1",
        0x2D,
        "RETURNDATASIZE",
        "DUP2",
        "PUSH1",
        0x09,
        "RETURNDATASIZE",
        "CODECOPY",
        "RETURN",
    ]
    forwarder_pre_asm = [
        "CALLDATASIZE",
        "RETURNDATASIZE",
        "RETURNDATASIZE",
        "CALLDATACOPY",
        "RETURNDATASIZE",
        "RETURNDATASIZE",
        "RETURNDATASIZE",
        "CALLDATASIZE",
        "RETURNDATASIZE",
        "PUSH20",  # [address to delegate to]
    ]
    forwarder_post_asm = [
        "GAS",
        "DELEGATECALL",
        "RETURNDATASIZE",
        "DUP3",
        "DUP1",
        "RETURNDATACOPY",
        "SWAP1",
        "RETURNDATASIZE",
        "SWAP2",
        "PUSH1",
        0x2B,  # jumpdest of whole program.
        "JUMPI",
        "REVERT",
        "JUMPDEST",
        "RETURN",
    ]
    return (
        assembly_to_evm(loader_asm)[0],
        assembly_to_evm(forwarder_pre_asm)[0],
        assembly_to_evm(forwarder_post_asm)[0],
    )


# "standard" initcode for code which can be larger than 256 bytes.
# returns the code starting from 0x0b with len `codesize`.
# NOTE: it assumes codesize <= 2**24.
def _create_preamble(codesize):

    from vyper.ir.compile_ir import assembly_to_evm

    evm_len = 0x0B  # 11 bytes
    asm = [
        # use PUSH3 to be able to deal with larger contracts
        "PUSH3",
        # blank space for codesize
        0x00,
        0x00,
        0x00,
        "RETURNDATASIZE",
        "DUP2",
        "PUSH1",
        evm_len,
        "RETURNDATASIZE",
        "CODECOPY",
        "RETURN",
    ]
    evm = assembly_to_evm(asm)[0]
    assert len(evm) == evm_len, evm

    shl_bits = (evm_len - 4) * 8  # codesize needs to go right after the PUSH3
    # mask codesize into the aforementioned "blank space"
    return ["or", bytes_to_int(evm), shl(shl_bits, codesize)], evm_len


class _CreateBase(BuiltinFunction):
    _kwargs = {
        "value": KwargSettings(Uint256Definition(), zero_value),
        "salt": KwargSettings(Bytes32Definition(), empty_value),
    }
    _return_type = AddressDefinition()

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        # errmsg something like "Cannot use {self._id} in pure fn"
        context.check_is_not_constant("use {self._id}", expr)

        should_use_create2 = "salt" in [kwarg.arg for kwarg in expr.keywords]
        if not should_use_create2:
            kwargs["salt"] = None

        ir_builder = self._build_create_IR(expr, args, context, **kwargs)

        add_gas_estimate = self._add_gas_estimate(args, should_use_create2)

        return IRnode.from_list(
            ir_builder,
            typ=BaseType("address"),
            annotation=self._id,
            add_gas_estimate=add_gas_estimate,
        )


class CreateMinimalProxyTo(_CreateBase):
    # create an EIP1167 "minimal proxy" to the target contract

    _id = "create_minimal_proxy_to"
    _inputs = [("target", AddressDefinition())]

    def _add_gas_estimate(self, args, should_use_create2):
        a, b, c = eip1167_bytecode()
        bytecode_len = 20 + len(b) + len(c)
        return _create_addl_gas_estimate(bytecode_len, should_use_create2)

    def _build_create_IR(self, expr, args, context, value, salt):

        target_address = args[0]

        buf = context.new_internal_variable(ByteArrayType(96))

        loader_evm, forwarder_pre_evm, forwarder_post_evm = eip1167_bytecode()
        # Adjust to 32-byte boundaries
        preamble_length = len(loader_evm) + len(forwarder_pre_evm)
        forwarder_preamble = bytes_to_int(
            loader_evm + forwarder_pre_evm + b"\x00" * (32 - preamble_length)
        )
        forwarder_post = bytes_to_int(forwarder_post_evm + b"\x00" * (32 - len(forwarder_post_evm)))

        # left-align the target
        if target_address.typ.is_literal:
            # note: should move to optimizer once we have
            # codesize optimization pipeline
            aligned_target = args[0].value << 96
        else:
            aligned_target = shl(96, target_address)

        buf_len = preamble_length + 20 + len(forwarder_post_evm)

        return [
            "seq",
            ["mstore", buf, forwarder_preamble],
            ["mstore", ["add", buf, preamble_length], aligned_target],
            ["mstore", ["add", buf, preamble_length + 20], forwarder_post],
            _create_ir(value, buf, buf_len, salt=salt),
        ]


class CreateForwarderTo(CreateMinimalProxyTo):
    _warned = False

    def build_IR(self, expr, context):
        if not self._warned:
            vyper_warn("`create_forwarder_to` is a deprecated alias of `create_minimal_proxy_to`!")
            self._warned = True

        return super().build_IR(expr, context)


class CreateCopyOf(_CreateBase):

    _id = "create_copy_of"
    _inputs = [("target", AddressDefinition())]

    @property
    def _preamble_len(self):
        return 11

    def _add_gas_estimate(self, args, should_use_create2):
        # max possible runtime length + preamble length
        return _create_addl_gas_estimate(EIP_170_LIMIT + self._preamble_len, should_use_create2)

    def _build_create_IR(self, expr, args, context, value, salt):
        target = args[0]

        with target.cache_when_complex("create_target") as (b1, target):
            codesize = IRnode.from_list(["extcodesize", target])
            msize = IRnode.from_list(["msize"])
            with codesize.cache_when_complex("target_codesize") as (
                b2,
                codesize,
            ), msize.cache_when_complex("mem_ofst") as (b3, mem_ofst):
                ir = ["seq"]

                # make sure there is actually code at the target
                ir.append(["assert", codesize])

                # store the preamble at msize + 22 (zero padding)
                preamble, preamble_len = _create_preamble(codesize)
                assert preamble_len == self._preamble_len

                ir.append(["mstore", mem_ofst, preamble])

                # copy the target code into memory. current layout:
                # msize | 00...00 (22 0's) | preamble | bytecode
                ir.append(["extcodecopy", target, add_ofst(mem_ofst, 32), 0, codesize])

                buf = add_ofst(mem_ofst, 32 - preamble_len)
                buf_len = ["add", codesize, preamble_len]

                ir.append(_create_ir(value, buf, buf_len, salt))

                return b1.resolve(b2.resolve(b3.resolve(ir)))


class CreateFromBlueprint(_CreateBase):

    _id = "create_from_blueprint"
    _inputs = [("target", AddressDefinition())]
    _kwargs = {
        "value": KwargSettings(Uint256Definition(), zero_value),
        "salt": KwargSettings(Bytes32Definition(), empty_value),
        "raw_args": KwargSettings(BoolDefinition(), False, require_literal=True),
        "code_offset": KwargSettings(Uint256Definition(), zero_value),
    }
    _has_varargs = True

    def _add_gas_estimate(self, args, should_use_create2):
        ctor_args = ir_tuple_from_args(args[1:])
        # max possible size of init code
        maxlen = EIP_170_LIMIT + ctor_args.typ.abi_type.size_bound()
        return _create_addl_gas_estimate(maxlen, should_use_create2)

    def _build_create_IR(self, expr, args, context, value, salt, code_offset, raw_args):
        target = args[0]
        ctor_args = args[1:]

        ctor_args = [ensure_in_memory(arg, context) for arg in ctor_args]

        if raw_args:
            if len(ctor_args) != 1 or not isinstance(ctor_args[0].typ, ByteArrayType):
                raise StructureException("raw_args must be used with exactly 1 bytes argument")

            argbuf = bytes_data_ptr(ctor_args[0])
            argslen = get_bytearray_length(ctor_args[0])
            bufsz = ctor_args[0].typ.maxlen
        else:
            # encode the varargs
            to_encode = ir_tuple_from_args(ctor_args)

            # pretend we allocated enough memory for the encoder
            # (we didn't, but we are clobbering unused memory so it's safe.)
            bufsz = to_encode.typ.abi_type.size_bound()
            argbuf = IRnode.from_list(
                context.new_internal_variable(get_type_for_exact_size(bufsz)), location=MEMORY
            )

            # return a complex expression which writes to memory and returns
            # the length of the encoded data
            argslen = abi_encode(argbuf, to_encode, context, bufsz=bufsz, returns_len=True)

        # NOTE: we need to invoke the abi encoder before evaluating MSIZE,
        # then copy the abi encoded buffer to past-the-end of the initcode
        # (since the abi encoder could write to fresh memory).
        # it would be good to not require the memory copy, but need
        # to evaluate memory safety.
        with target.cache_when_complex("create_target") as (b1, target), argslen.cache_when_complex(
            "encoded_args_len"
        ) as (b2, encoded_args_len), code_offset.cache_when_complex("code_ofst") as (b3, codeofst):
            codesize = IRnode.from_list(["sub", ["extcodesize", target], codeofst])
            # copy code to memory starting from msize. we are clobbering
            # unused memory so it's safe.
            msize = IRnode.from_list(["msize"], location=MEMORY)
            with codesize.cache_when_complex("target_codesize") as (
                b4,
                codesize,
            ), msize.cache_when_complex("mem_ofst") as (b5, mem_ofst):
                ir = ["seq"]

                # make sure there is code at the target, and that
                # code_ofst <= (extcodesize target).
                # (note if code_ofst > (extcodesize target), would be
                # OOG on the EXTCODECOPY)
                # (code_ofst == (extcodesize target) would be empty
                # initcode, which we disallow for hygiene reasons -
                # same as `create_copy_of` on an empty target).
                ir.append(["assert", ["sgt", codesize, 0]])

                # copy the target code into memory.
                # layout starting from mem_ofst:
                # 00...00 (22 0's) | preamble | bytecode
                ir.append(["extcodecopy", target, mem_ofst, codeofst, codesize])

                ir.append(copy_bytes(add_ofst(mem_ofst, codesize), argbuf, encoded_args_len, bufsz))

                # theoretically, dst = "msize", but just be safe.
                # if len(ctor_args) > 0:
                #    dst = add_ofst(mem_ofst, codesize)
                #    encoded_args_len = self._encode_args(dst, ctor_args, context)
                # else:
                #    encoded_args_len = 0

                length = ["add", codesize, encoded_args_len]

                ir.append(_create_ir(value, mem_ofst, length, salt))

                return b1.resolve(b2.resolve(b3.resolve(b4.resolve(b5.resolve(ir)))))


class _UnsafeMath(BuiltinFunction):

    # TODO add unsafe math for `decimal`s
    _inputs = [("a", IntegerAbstractType()), ("b", IntegerAbstractType())]

    def __repr__(self):
        return f"builtin function unsafe_{self.op}"

    def fetch_call_return(self, node):
        return_type = self.infer_arg_types(node).pop()
        return return_type

    def infer_arg_types(self, node):
        self._validate_arg_types(node)

        types_list = get_common_types(
            *node.args, filter_fn=lambda x: isinstance(x, IntegerAbstractType)
        )
        if not types_list:
            raise TypeMismatch(f"unsafe_{self.op} called on dislike types", node)

        type_ = types_list.pop()
        return [type_, type_]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        (a, b) = args
        op = self.op

        assert a.typ == b.typ, "unreachable"

        otyp = a.typ

        int_info = parse_integer_typeinfo(a.typ.typ)
        if op == "div" and int_info.is_signed:
            op = "sdiv"

        ret = [op, a, b]

        if int_info.bits < 256:
            # wrap for ops which could under/overflow
            if int_info.is_signed:
                # e.g. int128 -> (signextend 15 (add x y))
                ret = promote_signed_int(ret, int_info.bits)
            else:
                # e.g. uint8 -> (mod (add x y) 256)
                # TODO mod_bound could be a really large literal
                ret = ["mod", ret, 2 ** int_info.bits]

        return IRnode.from_list(ret, typ=otyp)

        # TODO handle decimal case


class UnsafeAdd(_UnsafeMath):
    op = "add"


class UnsafeSub(_UnsafeMath):
    op = "sub"


class UnsafeMul(_UnsafeMath):
    op = "mul"


class UnsafeDiv(_UnsafeMath):
    op = "div"


class _MinMax(BuiltinFunction):

    _inputs = [("a", NumericAbstractType()), ("b", NumericAbstractType())]

    def evaluate(self, node):
        validate_call_args(node, 2)
        if not isinstance(node.args[0], type(node.args[1])):
            raise UnfoldableNode
        if not isinstance(node.args[0], (vy_ast.Decimal, vy_ast.Int)):
            raise UnfoldableNode

        left, right = (i.value for i in node.args)
        if isinstance(left, Decimal) and (
            min(left, right) < -(2 ** 127) or max(left, right) >= 2 ** 127
        ):
            raise InvalidType("Decimal value is outside of allowable range", node)
        if isinstance(left, int) and (min(left, right) < 0 and max(left, right) >= 2 ** 127):
            raise TypeMismatch("Cannot perform action between dislike numeric types", node)

        value = self._eval_fn(left, right)
        return type(node.args[0]).from_node(node, value=value)

    def fetch_call_return(self, node):
        return_type = self.infer_arg_types(node).pop()
        return return_type

    def infer_arg_types(self, node):
        self._validate_arg_types(node)

        types_list = get_common_types(
            *node.args, filter_fn=lambda x: isinstance(x, NumericAbstractType)
        )
        if not types_list:
            raise TypeMismatch("Cannot perform action between dislike numeric types", node)

        type_ = types_list.pop()
        return [type_, type_]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        op = self._opcode

        with args[0].cache_when_complex("_l") as (b1, left), args[1].cache_when_complex("_r") as (
            b2,
            right,
        ):

            if left.typ.typ == right.typ.typ:
                if left.typ.typ != "uint256":
                    # if comparing like types that are not uint256, use SLT or SGT
                    op = f"s{op}"
                o = ["select", [op, left, right], left, right]
                otyp = left.typ
                otyp.is_literal = False

            else:
                raise TypeMismatch(f"Minmax types incompatible: {left.typ.typ} {right.typ.typ}")
            return IRnode.from_list(b1.resolve(b2.resolve(o)), typ=otyp)


class Min(_MinMax):
    _id = "min"
    _eval_fn = min
    _opcode = "lt"


class Max(_MinMax):
    _id = "max"
    _eval_fn = max
    _opcode = "gt"


class Uint2Str(BuiltinFunction):
    _id = "uint2str"
    _inputs = [("x", UnsignedIntegerAbstractType())]  # should allow any uint?

    def fetch_call_return(self, node):
        arg_t = self.infer_arg_types(node)[0]
        bits = arg_t._bits
        len_needed = math.ceil(bits * math.log(2) / math.log(10))
        return StringDefinition(len_needed)

    def evaluate(self, node):
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Int):
            raise UnfoldableNode

        value = str(node.args[0].value)
        return vy_ast.Str.from_node(node, value=value)

    def infer_arg_types(self, node):
        self._validate_arg_types(node)
        input_type = get_possible_types_from_node(node.args[0]).pop()
        return [input_type]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return_t = new_type_to_old_type(self.fetch_call_return(expr))
        n_digits = return_t.maxlen

        with args[0].cache_when_complex("val") as (b1, val):

            buf = context.new_internal_variable(return_t)

            i = IRnode.from_list(context.fresh_varname("uint2str_i"), typ="uint256")

            ret = ["repeat", i, 0, n_digits + 1, n_digits + 1]

            body = [
                "seq",
                [
                    "if",
                    ["eq", val, 0],
                    # clobber val, and return it as a pointer
                    [
                        "seq",
                        ["mstore", ["sub", buf + n_digits, i], i],
                        ["set", val, ["sub", buf + n_digits, i]],
                        "break",
                    ],
                    [
                        "seq",
                        ["mstore", ["sub", buf + n_digits, i], ["add", 48, ["mod", val, 10]]],
                        ["set", val, ["div", val, 10]],
                    ],
                ],
            ]
            ret.append(body)

            # "0" has hex representation 0x00..0130..00
            # if (val == 0) {
            #   return "0"
            # } else {
            #   do the loop
            # }
            ret = [
                "if",
                ["eq", val, 0],
                ["seq", ["mstore", buf + 1, ord("0")], ["mstore", buf, 1], buf],
                ["seq", ret, val],
            ]

            return b1.resolve(IRnode.from_list(ret, location=MEMORY, typ=return_t))


class Sqrt(BuiltinFunction):

    _id = "sqrt"
    _inputs = [("d", DecimalDefinition())]
    _return_type = DecimalDefinition()

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        # TODO check out this import
        from vyper.builtin_functions.utils import generate_inline_function

        arg = args[0]
        # TODO: reify decimal and integer sqrt paths (see isqrt)
        sqrt_code = """
assert x >= 0.0
z: decimal = 0.0

if x == 0.0:
    z = 0.0
else:
    z = x / 2.0 + 0.5
    y: decimal = x

    for i in range(256):
        if z == y:
            break
        y = z
        z = (x / z + z) / 2.0
        """

        x_type = BaseType("decimal")
        placeholder_copy = ["pass"]
        # Steal current position if variable is already allocated.
        if arg.value == "mload":
            new_var_pos = arg.args[0]
        # Other locations need to be copied.
        else:
            new_var_pos = context.new_internal_variable(x_type)
            placeholder_copy = ["mstore", new_var_pos, arg]
        # Create input variables.
        variables = {"x": VariableRecord(name="x", pos=new_var_pos, typ=x_type, mutable=False)}
        # Dictionary to update new (i.e. typecheck) namespace
        variables_2 = {"x": DecimalDefinition()}
        # Generate inline IR.
        new_ctx, sqrt_ir = generate_inline_function(
            code=sqrt_code,
            variables=variables,
            variables_2=variables_2,
            memory_allocator=context.memory_allocator,
        )
        return IRnode.from_list(
            ["seq", placeholder_copy, sqrt_ir, new_ctx.vars["z"].pos],  # load x variable
            typ=BaseType("decimal"),
            location=MEMORY,
        )


class ISqrt(BuiltinFunction):

    _id = "isqrt"
    _inputs = [("d", Uint256Definition())]
    _return_type = Uint256Definition()

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        # calculate isqrt using the babylonian method

        y, z = "y", "z"
        arg = args[0]
        with arg.cache_when_complex("x") as (b1, x):
            ret = [
                "seq",
                [
                    "if",
                    ["ge", y, 2 ** (128 + 8)],
                    ["seq", ["set", y, shr(128, y)], ["set", z, shl(64, z)]],
                ],
                [
                    "if",
                    ["ge", y, 2 ** (64 + 8)],
                    ["seq", ["set", y, shr(64, y)], ["set", z, shl(32, z)]],
                ],
                [
                    "if",
                    ["ge", y, 2 ** (32 + 8)],
                    ["seq", ["set", y, shr(32, y)], ["set", z, shl(16, z)]],
                ],
                [
                    "if",
                    ["ge", y, 2 ** (16 + 8)],
                    ["seq", ["set", y, shr(16, y)], ["set", z, shl(8, z)]],
                ],
            ]
            ret.append(["set", z, ["div", ["mul", z, ["add", y, 2 ** 16]], 2 ** 18]])

            for _ in range(7):
                ret.append(["set", z, ["div", ["add", ["div", x, z], z], 2]])

            # note: If ``x+1`` is a perfect square, then the Babylonian
            # algorithm oscillates between floor(sqrt(x)) and ceil(sqrt(x)) in
            # consecutive iterations. return the floor value always.

            ret.append(["with", "t", ["div", x, z], ["select", ["lt", z, "t"], z, "t"]])

            ret = ["with", y, x, ["with", z, 181, ret]]
            return b1.resolve(IRnode.from_list(ret, typ=BaseType("uint256")))


class Empty(TypenameFoldedFunction):

    _id = "empty"

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        output_type = args[0]
        return IRnode("~empty", typ=output_type)


class Breakpoint(BuiltinFunction):
    _id = "breakpoint"
    _inputs: list = []

    _warned = False

    def fetch_call_return(self, node):
        if not self._warned:
            vyper_warn("`breakpoint` should only be used for debugging!\n" + node._annotated_source)
            self._warned = True

        return None

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list("breakpoint", annotation="breakpoint()")


class Print(BuiltinFunction):
    _id = "print"
    _inputs: list = []
    _has_varargs = True
    _kwargs = {"hardhat_compat": KwargSettings(BoolDefinition(), False, require_literal=True)}

    _warned = False

    def fetch_call_return(self, node):
        if not self._warned:
            vyper_warn("`print` should only be used for debugging!\n" + node._annotated_source)
            self._warned = True

        return None

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        args_as_tuple = ir_tuple_from_args(args)
        args_abi_t = args_as_tuple.typ.abi_type

        # create a signature like "log(uint256)"
        sig = "log" + "(" + ",".join([arg.typ.abi_type.selector_name() for arg in args]) + ")"

        if kwargs["hardhat_compat"] is True:
            method_id = abi_method_id(sig)
            buflen = 32 + args_abi_t.size_bound()

            # 32 bytes extra space for the method id
            buf = context.new_internal_variable(get_type_for_exact_size(buflen))

            ret = ["seq"]
            ret.append(["mstore", buf, method_id])
            encode = abi_encode(buf + 32, args_as_tuple, context, buflen, returns_len=True)

        else:
            method_id = abi_method_id("log(string,bytes)")
            schema = args_abi_t.selector_name().encode("utf-8")
            if len(schema) > 32:
                raise CompilerPanic("print signature too long: {schema}")

            schema_t = StringType(len(schema))
            schema_buf = context.new_internal_variable(schema_t)
            ret = ["seq"]
            ret.append(["mstore", schema_buf, len(schema)])

            # TODO use Expr.make_bytelike, or better have a `bytestring` IRnode type
            ret.append(["mstore", schema_buf + 32, bytes_to_int(schema.ljust(32, b"\x00"))])

            payload_buflen = args_abi_t.size_bound()
            payload_t = ByteArrayType(payload_buflen)

            # 32 bytes extra space for the method id
            payload_buf = context.new_internal_variable(payload_t)
            encode_payload = abi_encode(
                payload_buf + 32, args_as_tuple, context, payload_buflen, returns_len=True
            )

            ret.append(["mstore", payload_buf, encode_payload])
            args_as_tuple = ir_tuple_from_args(
                [
                    IRnode.from_list(schema_buf, typ=schema_t, location=MEMORY),
                    IRnode.from_list(payload_buf, typ=payload_t, location=MEMORY),
                ]
            )

            # add 32 for method id padding
            buflen = 32 + args_as_tuple.typ.abi_type.size_bound()
            buf = context.new_internal_variable(get_type_for_exact_size(buflen))
            ret.append(["mstore", buf, method_id])
            encode = abi_encode(buf + 32, args_as_tuple, context, buflen, returns_len=True)

        # debug address that tooling uses
        CONSOLE_ADDRESS = 0x000000000000000000636F6E736F6C652E6C6F67
        ret.append(["staticcall", "gas", CONSOLE_ADDRESS, buf + 28, ["add", 4, encode], 0, 0])

        return IRnode.from_list(ret, annotation="print:" + sig)


class ABIEncode(BuiltinFunction):
    _id = "_abi_encode"  # TODO prettier to rename this to abi.encode
    # signature: *, ensure_tuple=<literal_bool> -> Bytes[<calculated len>]
    # (check the signature manually since we have no utility methods
    # to handle varargs.)
    # explanation of ensure_tuple:
    # default is to force even a single value into a tuple,
    # e.g. _abi_encode(bytes) -> _abi_encode((bytes,))
    #      _abi_encode((bytes,)) -> _abi_encode(((bytes,),))
    # this follows the encoding convention for functions:
    # ://docs.soliditylang.org/en/v0.8.6/abi-spec.html#function-selector-and-argument-encoding
    # if this is turned off, then bytes will be encoded as bytes.

    _inputs: list = []
    _has_varargs = True

    _kwargs = {
        "ensure_tuple": KwargSettings(BoolDefinition(), True, require_literal=True),
        "method_id": KwargSettings(
            (Bytes4Definition(), BytesArrayDefinition(4)), None, require_literal=True
        ),
    }

    def infer_kwarg_types(self, node):
        ret = {}
        for kwarg in node.keywords:
            kwarg_name = kwarg.arg
            validate_expected_type(kwarg.value, self._kwargs[kwarg_name].typ)
            ret[kwarg_name] = get_exact_type_from_node(kwarg.value)
        return ret

    def fetch_call_return(self, node):
        self._validate_arg_types(node)
        ensure_tuple = next(
            (arg.value.value for arg in node.keywords if arg.arg == "ensure_tuple"), True
        )
        assert isinstance(ensure_tuple, bool)
        has_method_id = "method_id" in [arg.arg for arg in node.keywords]

        # figure out the output type by converting
        # the types to ABI_Types and calling size_bound API
        arg_abi_types = []
        arg_types = self.infer_arg_types(node)
        for arg_t in arg_types:
            arg_abi_types.append(arg_t.abi_type)

        # special case, no tuple
        if len(arg_abi_types) == 1 and not ensure_tuple:
            arg_abi_t = arg_abi_types[0]
        else:
            arg_abi_t = ABI_Tuple(arg_abi_types)

        maxlen = arg_abi_t.size_bound()

        if has_method_id:
            # the output includes 4 bytes for the method_id.
            maxlen += 4

        ret = BytesArrayDefinition()
        ret.set_length(maxlen)
        return ret

    @staticmethod
    def _parse_method_id(method_id_literal):
        if method_id_literal is None:
            return None
        if isinstance(method_id_literal, bytes):
            assert len(method_id_literal) == 4
            return fourbytes_to_int(method_id_literal)
        if method_id_literal.startswith("0x"):
            method_id_literal = method_id_literal[2:]
        return fourbytes_to_int(bytes.fromhex(method_id_literal))

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        ensure_tuple = kwargs["ensure_tuple"]
        method_id = self._parse_method_id(kwargs["method_id"])

        if len(args) < 1:
            raise StructureException("abi_encode expects at least one argument", expr)

        # figure out the required length for the output buffer
        if len(args) == 1 and not ensure_tuple:
            # special case, no tuple
            encode_input = args[0]
        else:
            encode_input = ir_tuple_from_args(args)

        input_abi_t = encode_input.typ.abi_type
        maxlen = input_abi_t.size_bound()
        if method_id is not None:
            maxlen += 4

        buf_t = ByteArrayType(maxlen=maxlen)
        assert self.fetch_call_return(expr).length == maxlen
        buf = context.new_internal_variable(buf_t)

        ret = ["seq"]
        if method_id is not None:
            # <32 bytes length> | <4 bytes method_id> | <everything else>
            # write the unaligned method_id first, then we will
            # overwrite the 28 bytes of zeros with the bytestring length
            ret += [["mstore", buf + 4, method_id]]
            # abi encode, and grab length as stack item
            length = abi_encode(buf + 36, encode_input, context, returns_len=True, bufsz=maxlen)
            # write the output length to where bytestring stores its length
            ret += [["mstore", buf, ["add", length, 4]]]

        else:
            # abi encode and grab length as stack item
            length = abi_encode(buf + 32, encode_input, context, returns_len=True, bufsz=maxlen)
            # write the output length to where bytestring stores its length
            ret += [["mstore", buf, length]]

        # return the buf location
        # TODO location is statically known, optimize this out
        ret += [buf]

        return IRnode.from_list(ret, location=MEMORY, typ=buf_t)


class ABIDecode(BuiltinFunction):
    _id = "_abi_decode"
    _inputs = [("data", BytesArrayPrimitive()), ("output_type", "TYPE_DEFINITION")]
    _kwargs = {"unwrap_tuple": KwargSettings(BoolDefinition(), True, require_literal=True)}

    def fetch_call_return(self, node):
        _, output_type = self.infer_arg_types(node)
        return output_type.typedef

    def infer_arg_types(self, node):
        validate_call_args(node, 2, ["unwrap_tuple"])

        data_type = get_exact_type_from_node(node.args[0])
        output_typedef = TypeTypeDefinition(
            get_type_from_annotation(node.args[1], DataLocation.MEMORY)
        )

        return [data_type, output_typedef]

    @process_inputs
    def build_IR(self, expr, args, kwargs, context):
        unwrap_tuple = kwargs["unwrap_tuple"]

        data = args[0]
        output_typ = args[1]
        wrapped_typ = output_typ

        if unwrap_tuple is True:
            wrapped_typ = calculate_type_for_external_return(output_typ)

        abi_size_bound = wrapped_typ.abi_type.size_bound()
        abi_min_size = wrapped_typ.abi_type.min_size()

        # Get the size of data
        input_max_len = data.typ.maxlen

        assert abi_min_size <= abi_size_bound, "bad abi type"
        if input_max_len < abi_size_bound:
            raise StructureException(
                (
                    "Mismatch between size of input and size of decoded types. "
                    f"length of ABI-encoded {wrapped_typ} must be equal to or greater "
                    f"than {abi_size_bound}"
                ),
                expr.args[0],
            )

        data = ensure_in_memory(data, context)
        with data.cache_when_complex("to_decode") as (b1, data):

            data_ptr = bytes_data_ptr(data)
            data_len = get_bytearray_length(data)

            # Normally, ABI-encoded data assumes the argument is a tuple
            # (See comments for `wrap_value_for_external_return`)
            # However, we do not want to use `wrap_value_for_external_return`
            # technique as used in external call codegen because in order to be
            # type-safe we would need an extra memory copy. To avoid a copy,
            # we manually add the ABI-dynamic offset so that it is
            # re-interpreted in-place.
            if (
                unwrap_tuple is True
                and needs_external_call_wrap(output_typ)
                and output_typ.abi_type.is_dynamic()
            ):
                data_ptr = add_ofst(data_ptr, 32)

            ret = ["seq"]

            if abi_min_size == abi_size_bound:
                ret.append(["assert", ["eq", abi_min_size, data_len]])
            else:
                # runtime assert: abi_min_size <= data_len <= abi_size_bound
                ret.append(clamp2(abi_min_size, data_len, abi_size_bound, signed=False))

            # return pointer to the buffer
            ret.append(data_ptr)

            return b1.resolve(
                IRnode.from_list(
                    ret,
                    typ=output_typ,
                    location=data.location,
                    encoding=Encoding.ABI,
                    annotation=f"abi_decode({output_typ})",
                )
            )


class _MinMaxValue(TypenameFoldedFunction):
    def evaluate(self, node):
        self._validate_arg_types(node)
        input_type = get_type_from_annotation(node.args[0], DataLocation.UNSET)

        if not isinstance(input_type, NumericAbstractType):
            raise InvalidType(f"Expected numeric type but got {input_type} instead", node)

        if isinstance(input_type, DecimalDefinition):
            val = self._eval_decimal(input_type)
            return vy_ast.Decimal.from_node(node, value=val)

        if isinstance(input_type, IntegerAbstractType):
            val = self._eval_int(input_type)
            return vy_ast.Int.from_node(node, value=val)


class MinValue(_MinMaxValue):
    _id = "min_value"

    def _eval_int(self, type_):
        typinfo = parse_integer_typeinfo(str(type_))
        return typinfo.bounds[0]

    def _eval_decimal(self, type_):
        typinfo = parse_decimal_info(str(type_))
        return typinfo.decimal_bounds[0]


class MaxValue(_MinMaxValue):
    _id = "max_value"

    def _eval_int(self, type_):
        typinfo = parse_integer_typeinfo(str(type_))
        return typinfo.bounds[1]

    def _eval_decimal(self, type_):
        typinfo = parse_decimal_info(str(type_))
        return typinfo.decimal_bounds[1]


class Epsilon(TypenameFoldedFunction):
    _id = "epsilon"

    def evaluate(self, node):
        self._validate_arg_types(node)
        input_type = get_type_from_annotation(node.args[0], DataLocation.UNSET)

        if not isinstance(input_type, FixedAbstractType):
            raise InvalidType(f"Expected decimal type but got {input_type} instead", node)

        # this check seems redundant, but sets a pattern to be followed
        # when new decimal types are created
        if isinstance(input_type, DecimalDefinition):
            typinfo = parse_decimal_info(str(input_type))
            return vy_ast.Decimal.from_node(node, value=typinfo.epsilon)

        raise CompilerPanic("unreachable")  # pragma: notest


DISPATCH_TABLE = {
    "_abi_encode": ABIEncode(),
    "_abi_decode": ABIDecode(),
    "floor": Floor(),
    "ceil": Ceil(),
    "convert": Convert(),
    "slice": Slice(),
    "len": Len(),
    "concat": Concat(),
    "sha256": Sha256(),
    "method_id": MethodID(),
    "keccak256": Keccak256(),
    "ecrecover": ECRecover(),
    "ecadd": ECAdd(),
    "ecmul": ECMul(),
    "extract32": Extract32(),
    "as_wei_value": AsWeiValue(),
    "raw_call": RawCall(),
    "blockhash": BlockHash(),
    "bitwise_and": BitwiseAnd(),
    "bitwise_or": BitwiseOr(),
    "bitwise_xor": BitwiseXor(),
    "bitwise_not": BitwiseNot(),
    "uint256_addmod": AddMod(),
    "uint256_mulmod": MulMod(),
    "unsafe_add": UnsafeAdd(),
    "unsafe_sub": UnsafeSub(),
    "unsafe_mul": UnsafeMul(),
    "unsafe_div": UnsafeDiv(),
    "pow_mod256": PowMod256(),
    "uint2str": Uint2Str(),
    "isqrt": ISqrt(),
    "sqrt": Sqrt(),
    "shift": Shift(),
    "create_minimal_proxy_to": CreateMinimalProxyTo(),
    "create_forwarder_to": CreateForwarderTo(),
    "create_copy_of": CreateCopyOf(),
    "create_from_blueprint": CreateFromBlueprint(),
    "min": Min(),
    "max": Max(),
    "empty": Empty(),
    "abs": Abs(),
    "min_value": MinValue(),
    "max_value": MaxValue(),
    "epsilon": Epsilon(),
}

STMT_DISPATCH_TABLE = {
    "send": Send(),
    "print": Print(),
    "breakpoint": Breakpoint(),
    "selfdestruct": SelfDestruct(),
    "raw_call": RawCall(),
    "raw_log": RawLog(),
    "create_minimal_proxy_to": CreateMinimalProxyTo(),
    "create_forwarder_to": CreateForwarderTo(),
    "create_copy_of": CreateCopyOf(),
    "create_from_blueprint": CreateFromBlueprint(),
}

BUILTIN_FUNCTIONS = {**STMT_DISPATCH_TABLE, **DISPATCH_TABLE}.keys()


def get_builtin_functions():
    return {**STMT_DISPATCH_TABLE, **DISPATCH_TABLE}
