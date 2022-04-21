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
    add_ofst,
    bytes_data_ptr,
    check_external_call,
    clamp_basetype,
    copy_bytes,
    ensure_in_memory,
    eval_seq,
    get_bytearray_length,
    get_element_ptr,
    ir_tuple_from_args,
    promote_signed_int,
    unwrap_location,
)
from vyper.codegen.expr import Expr
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
    is_bytes_m_type,
    parse_integer_typeinfo,
)
from vyper.evm.opcodes import version_check
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
    VyperException,
    ZeroDivisionException,
)
from vyper.semantics.types import BoolDefinition, DynamicArrayPrimitive, TupleDefinition
from vyper.semantics.types.abstract import (
    ArrayValueAbstractType,
    BytesAbstractType,
    IntegerAbstractType,
    NumericAbstractType,
    SignedIntegerAbstractType,
)
from vyper.semantics.types.bases import DataLocation, ValueTypeDefinition
from vyper.semantics.types.indexable.sequence import ArrayDefinition
from vyper.semantics.types.utils import get_type_from_annotation
from vyper.semantics.types.value.address import AddressDefinition
from vyper.semantics.types.value.array_value import (
    BytesArrayDefinition,
    BytesArrayPrimitive,
    StringDefinition,
    StringPrimitive,
)
from vyper.semantics.types.value.bytes_fixed import Bytes32Definition
from vyper.semantics.types.value.numeric import Int256Definition  # type: ignore
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
    MemoryPositions,
    SizeLimits,
    abi_method_id,
    bytes_to_int,
    fourbytes_to_int,
    keccak256,
    vyper_warn,
)

from .signatures import Optional, validate_inputs

SHA256_ADDRESS = 2
SHA256_BASE_GAS = 60
SHA256_PER_WORD_GAS = 12


class _SimpleBuiltinFunction:
    def fetch_call_return(self, node):
        validate_call_args(node, len(self._inputs), getattr(self, "_kwargs", []))
        for arg, (_, expected) in zip(node.args, self._inputs):
            validate_expected_type(arg, expected)

        if self._return_type:
            return self._return_type


class Floor(_SimpleBuiltinFunction):

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

    @validate_inputs
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


class Ceil(_SimpleBuiltinFunction):

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

    @validate_inputs
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


class Convert:

    _id = "convert"

    def fetch_call_return(self, node):
        validate_call_args(node, 2)
        target_type = get_type_from_annotation(node.args[1], DataLocation.MEMORY)
        validate_expected_type(node.args[0], ValueTypeDefinition())

        # block conversions between same type
        try:
            validate_expected_type(node.args[0], target_type)
        except VyperException:
            pass
        else:
            if not isinstance(target_type, Uint256Definition):
                raise InvalidType(f"Value and target type are both '{target_type}'", node)

        # note: more type conversion validation happens in convert.py
        return target_type

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
                [
                    "assert",
                    ["le", ["add", start, length], ["extcodesize", "_extcode_address"]],
                ],
                ["mstore", np, length],
                ["extcodecopy", "_extcode_address", np + 32, start, length],
                np,
            ],
        ]

    return IRnode.from_list(node, typ=ByteArrayType(length.value), location=MEMORY)


class Slice:

    _id = "slice"
    _inputs = [("b", ("Bytes", "bytes32", "String")), ("start", "uint256"), ("length", "uint256")]
    _return_type = None

    def fetch_call_return(self, node):
        validate_call_args(node, 3)

        validate_expected_type(node.args[0], (BytesAbstractType(), StringPrimitive()))

        arg_type = get_possible_types_from_node(node.args[0]).pop()

        try:
            validate_expected_type(node.args[0], StringPrimitive())
            return_type = StringDefinition()
        except VyperException:
            return_type = BytesArrayDefinition()

        for arg in node.args[1:]:
            validate_expected_type(arg, Uint256Definition())

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
                    raise ArgumentException("slice out of bounds for {arg_type}", start_expr)
                if length_literal is not None and start_literal + length_literal > arg_type.length:
                    raise ArgumentException("slice out of bounds for {arg_type}", node)

        # we know the length statically
        if length_literal is not None:
            return_type.set_length(length_literal)
        else:
            return_type.set_min_length(arg_type.length)

        return return_type

    @validate_inputs
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
                    ["add", src_data, ["div", start, 32]],
                    location=src.location,
                )

                # e.g. start == byte 0 -> we copy to dst_data + 0
                #      start == byte 7 -> we copy to dst_data - 7
                #      start == byte 33 -> we copy to dst_data - 1
                # TODO add optimizer rule for modulus-powers-of-two
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

            do_copy = copy_bytes(
                copy_dst,
                copy_src,
                copy_len,
                copy_maxlen,
            )

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


class Len(_SimpleBuiltinFunction):

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


class Concat:

    _id = "concat"

    def fetch_call_return(self, node):
        if len(node.args) < 2:
            raise ArgumentException("Invalid argument count: expected at least 2", node)

        if node.keywords:
            raise ArgumentException("Keyword arguments are not accepted here", node.keywords[0])

        type_ = None
        for expected in (BytesAbstractType(), StringPrimitive()):
            try:
                validate_expected_type(node.args[0], expected)
                type_ = expected
            except (InvalidType, TypeMismatch):
                pass
        if type_ is None:
            raise TypeMismatch("Concat values must be bytes or string", node.args[0])

        length = 0
        for arg in node.args[1:]:
            validate_expected_type(arg, type_)

        length = 0
        for arg in node.args:
            length += get_possible_types_from_node(arg).pop().length

        if isinstance(type_, BytesAbstractType):
            return_type = BytesArrayDefinition()
        else:
            return_type = StringDefinition()
        return_type.set_length(length)
        return return_type

    def build_IR(self, expr, context):
        args = [Expr(arg, context).ir_node for arg in expr.args]
        if len(args) < 2:
            raise StructureException("Concat expects at least two arguments", expr)

        prev_type = ""
        for _, (expr_arg, arg) in enumerate(zip(expr.args, args)):
            if not isinstance(arg.typ, ByteArrayLike) and not is_bytes_m_type(arg.typ):
                raise TypeMismatch("Concat expects string, bytes or bytes32 objects", expr_arg)

            current_type = (
                "Bytes"
                if isinstance(arg.typ, ByteArrayType) or is_bytes_m_type(arg.typ)
                else "String"
            )
            if prev_type and current_type != prev_type:
                raise TypeMismatch(
                    (
                        "Concat expects consistent use of string or byte types, "
                        "user either bytes or string."
                    ),
                    expr_arg,
                )
            prev_type = current_type

        # Maximum length of the output
        dst_maxlen = sum(
            [
                arg.typ.maxlen if isinstance(arg.typ, ByteArrayLike) else arg.typ._bytes_info.m
                for arg in args
            ]
        )

        if current_type == "String":
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
            ["with", ofst, 0, ret],
            typ=ret_typ,
            location=MEMORY,
            annotation="concat",
        )


class Keccak256(_SimpleBuiltinFunction):

    _id = "keccak256"
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

        hash_ = f"0x{keccak256(value).hex()}"
        return vy_ast.Hex.from_node(node, value=hash_)

    @validate_inputs
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


class Sha256(_SimpleBuiltinFunction):

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

    @validate_inputs
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


class MethodID:

    _id = "method_id"

    def evaluate(self, node):
        validate_call_args(node, 1, ["output_type"])

        args = node.args
        if not isinstance(args[0], vy_ast.Str):
            raise InvalidType("method id must be given as a literal string", args[0])
        if " " in args[0].value:
            raise InvalidLiteral("Invalid function signature - no spaces allowed.")

        if node.keywords:
            return_type = get_type_from_annotation(node.keywords[0].value, DataLocation.UNSET)
            if isinstance(return_type, Bytes32Definition):
                length = 32
            elif isinstance(return_type, BytesArrayDefinition) and return_type.length == 4:
                length = 4
            else:
                raise ArgumentException("output_type must be bytes[4] or bytes32", node.keywords[0])
        else:
            # if `output_type` is not given, default to `bytes[4]`
            length = 4

        method_id = fourbytes_to_int(keccak256(args[0].value.encode())[:4])
        value = method_id.to_bytes(length, "big")

        if length == 32:
            return vy_ast.Hex.from_node(node, value=f"0x{value.hex()}")
        elif length == 4:
            return vy_ast.Bytes.from_node(node, value=value)
        else:
            raise CompilerPanic

    def fetch_call_return(self, node):
        raise CompilerPanic("method_id should always be folded")

    def build_IR(self, *args, **kwargs):
        raise CompilerPanic("method_id should always be folded")


class ECRecover(_SimpleBuiltinFunction):

    _id = "ecrecover"
    _inputs = [
        ("hash", Bytes32Definition()),
        ("v", Uint256Definition()),
        ("r", Uint256Definition()),
        ("s", Uint256Definition()),
    ]
    _return_type = AddressDefinition()

    @validate_inputs
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


class ECAdd(_SimpleBuiltinFunction):

    _id = "ecadd"
    _inputs = [
        ("a", ArrayDefinition(Uint256Definition(), 2)),
        ("b", ArrayDefinition(Uint256Definition(), 2)),
    ]
    _return_type = ArrayDefinition(Uint256Definition(), 2)

    @validate_inputs
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


class ECMul(_SimpleBuiltinFunction):

    _id = "ecmul"
    _inputs = [("point", ArrayDefinition(Uint256Definition(), 2)), ("scalar", Uint256Definition())]
    _return_type = ArrayDefinition(Uint256Definition(), 2)

    @validate_inputs
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
            [op, ["add", "_sub", ["add", 32, ["mul", 32, index]]]],
            typ=BaseType("int128"),
        )

    return f


def _storage_element_getter(index):
    return IRnode.from_list(
        ["sload", ["add", "_sub", ["add", 1, index]]],
        typ=BaseType("int128"),
    )


class Extract32(_SimpleBuiltinFunction):

    _id = "extract32"
    _inputs = [("b", BytesArrayPrimitive()), ("start", SignedIntegerAbstractType())]
    _kwargs = {"output_type": Optional("name_literal", "bytes32")}
    _return_type = None

    def fetch_call_return(self, node):
        super().fetch_call_return(node)
        if node.keywords:
            return_type = get_type_from_annotation(node.keywords[0].value, DataLocation.MEMORY)
            if not isinstance(
                return_type, (AddressDefinition, Bytes32Definition, IntegerAbstractType)
            ):
                raise
        else:
            return_type = Bytes32Definition()

        return return_type

    @validate_inputs
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
                    elementgetter(["div", ["clamp", 0, index, ["sub", lengetter, 32]], 32]),
                ],
                typ=BaseType(ret_type),
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
                            ["clamp", 0, index, ["sub", "_len", 32]],
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
                typ=BaseType(ret_type),
                annotation="extract32",
            )
        return IRnode.from_list(
            clamp_basetype(o),
            typ=ret_type,
        )


class AsWeiValue:

    _id = "as_wei_value"
    _inputs = [("value", NumericAbstractType()), ("unit", "str_literal")]
    _return_type = Uint256Definition()

    wei_denoms = {
        ("wei",): 1,
        ("femtoether", "kwei", "babbage"): 10 ** 3,
        ("picoether", "mwei", "lovelace"): 10 ** 6,
        ("nanoether", "gwei", "shannon"): 10 ** 9,
        (
            "microether",
            "szabo",
        ): 10
        ** 12,
        (
            "milliether",
            "finney",
        ): 10
        ** 15,
        ("ether",): 10 ** 18,
        ("kether", "grand"): 10 ** 21,
    }

    def evaluate(self, node):
        validate_call_args(node, 2)
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
        validate_expected_type(node.args[0], NumericAbstractType())
        return self._return_type

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        value, denom_name = args[0], args[1].decode()

        denom_divisor = next(v for k, v in self.wei_denoms.items() if denom_name in k)
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
            sub = [
                "seq",
                ["assert", ["sgt", value, -1]],
                ["mul", value, denom_divisor],
            ]
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
false_value = IRnode.from_list(0, typ=BaseType("bool", is_literal=True))
true_value = IRnode.from_list(1, typ=BaseType("bool", is_literal=True))


class RawCall(_SimpleBuiltinFunction):

    _id = "raw_call"
    _inputs = [("to", AddressDefinition()), ("data", BytesArrayPrimitive())]
    _kwargs = {
        "max_outsize": Optional("num_literal", 0),
        "gas": Optional("uint256", "gas"),
        "value": Optional("uint256", zero_value),
        "is_delegate_call": Optional("bool", false_value),
        "is_static_call": Optional("bool", false_value),
        "revert_on_failure": Optional("bool", true_value),
    }
    _return_type = None

    def fetch_call_return(self, node):
        super().fetch_call_return(node)

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

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        to, data = args
        gas, value, outsize, delegate_call, static_call, revert_on_failure = (
            kwargs["gas"],
            kwargs["value"],
            kwargs["max_outsize"],
            kwargs["is_delegate_call"],
            kwargs["is_static_call"],
            kwargs["revert_on_failure"],
        )
        for key in ("is_delegate_call", "is_static_call", "revert_on_failure"):
            if kwargs[key].typ.is_literal is False:
                raise TypeMismatch(
                    f"The `{key}` parameter must be a static/literal boolean value", expr
                )
        # turn IR literals into python values
        revert_on_failure = revert_on_failure.value == 1
        static_call = static_call.value == 1
        delegate_call = delegate_call.value == 1

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

        eval_input_buf = ensure_in_memory(data, context)
        input_buf = eval_seq(eval_input_buf)

        output_node = IRnode.from_list(
            context.new_internal_variable(ByteArrayType(outsize)),
            typ=ByteArrayType(outsize),
            location=MEMORY,
        )

        bool_ty = BaseType("bool")

        if input_buf is None:
            call_ir = ["with", "arg_buf", eval_input_buf]
            input_buf = IRnode.from_list("arg_buf")
        else:
            call_ir = ["seq", eval_input_buf]

        # build IR for call or delegatecall
        common_call_args = [
            add_ofst(input_buf, 32),
            ["mload", input_buf],  # buf len
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
            size = [
                "with",
                "_l",
                outsize,
                ["with", "_r", "returndatasize", ["if", ["gt", "_l", "_r"], "_r", "_l"]],
            ]

            # store output size and return output location
            store_output_size = [
                "with",
                "output_pos",
                output_node,
                ["seq", ["mstore", "output_pos", size], "output_pos"],
            ]

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


class Send(_SimpleBuiltinFunction):

    _id = "send"
    _inputs = [("to", AddressDefinition()), ("value", Uint256Definition())]
    _return_type = None

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        to, value = args
        if context.is_constant():
            raise StateAccessViolation(
                f"Cannot send ether inside {context.pp_constancy()}!",
                expr,
            )
        return IRnode.from_list(
            ["assert", ["call", 0, to, value, 0, 0, 0, 0]],
        )


class SelfDestruct(_SimpleBuiltinFunction):

    _id = "selfdestruct"
    _inputs = [("to", AddressDefinition())]
    _return_type = None
    _is_terminus = True

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        if context.is_constant():
            raise StateAccessViolation(
                f"Cannot {expr.func.id} inside {context.pp_constancy()}!",
                expr.func,
            )
        return IRnode.from_list(["selfdestruct", args[0]])


class BlockHash(_SimpleBuiltinFunction):

    _id = "blockhash"
    _inputs = [("block_num", Uint256Definition())]
    _return_type = Bytes32Definition()

    @validate_inputs
    def build_IR(self, expr, args, kwargs, contact):
        return IRnode.from_list(
            ["blockhash", ["uclamplt", ["clampge", args[0], ["sub", ["number"], 256]], "number"]],
            typ=BaseType("bytes32"),
        )


class RawLog:

    _id = "raw_log"
    _inputs = [("topics", "*"), ("data", ("bytes32", "Bytes"))]

    def fetch_call_return(self, node):
        validate_call_args(node, 2)
        if not isinstance(node.args[0], vy_ast.List) or len(node.args[0].elements) > 4:
            raise InvalidType("Expecting a list of 0-4 topics as first argument", node.args[0])
        if node.args[0].elements:
            validate_expected_type(
                node.args[0], ArrayDefinition(Bytes32Definition(), len(node.args[0].elements))
            )
        validate_expected_type(node.args[1], BytesAbstractType())

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        if not isinstance(args[0], vy_ast.List) or len(args[0].elements) > 4:
            raise StructureException("Expecting a list of 0-4 topics as first argument", args[0])
        topics = []
        for elt in args[0].elements:
            arg = Expr.parse_value_expr(elt, context)
            if not is_base_type(arg.typ, "bytes32"):
                raise TypeMismatch("Expecting a bytes32 argument as topic", elt)
            topics.append(arg)
        if args[1].typ == BaseType("bytes32"):
            placeholder = context.new_internal_variable(BaseType("bytes32"))
            return IRnode.from_list(
                [
                    "seq",
                    # TODO use make_setter
                    ["mstore", placeholder, unwrap_location(args[1])],
                    ["log" + str(len(topics)), placeholder, 32] + topics,
                ],
            )

        input_buf = ensure_in_memory(args[1], context)

        return IRnode.from_list(
            [
                "with",
                "_sub",
                input_buf,
                ["log" + str(len(topics)), ["add", "_sub", 32], ["mload", "_sub"], *topics],
            ],
        )


class BitwiseAnd(_SimpleBuiltinFunction):

    _id = "bitwise_and"
    _inputs = [("x", Uint256Definition()), ("y", Uint256Definition())]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 2)
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = node.args[0].value & node.args[1].value
        return vy_ast.Int.from_node(node, value=value)

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["and", args[0], args[1]], typ=BaseType("uint256"))


class BitwiseOr(_SimpleBuiltinFunction):

    _id = "bitwise_or"
    _inputs = [("x", Uint256Definition()), ("y", Uint256Definition())]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 2)
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = node.args[0].value | node.args[1].value
        return vy_ast.Int.from_node(node, value=value)

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["or", args[0], args[1]], typ=BaseType("uint256"))


class BitwiseXor(_SimpleBuiltinFunction):

    _id = "bitwise_xor"
    _inputs = [("x", Uint256Definition()), ("y", Uint256Definition())]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 2)
        for arg in node.args:
            if not isinstance(arg, vy_ast.Num):
                raise UnfoldableNode
            if arg.value < 0 or arg.value >= 2 ** 256:
                raise InvalidLiteral("Value out of range for uint256", arg)

        value = node.args[0].value ^ node.args[1].value
        return vy_ast.Int.from_node(node, value=value)

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["xor", args[0], args[1]], typ=BaseType("uint256"))


class BitwiseNot(_SimpleBuiltinFunction):

    _id = "bitwise_not"
    _inputs = [("x", Uint256Definition())]
    _return_type = Uint256Definition()

    def evaluate(self, node):
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Num):
            raise UnfoldableNode

        value = node.args[0].value
        if value < 0 or value >= 2 ** 256:
            raise InvalidLiteral("Value out of range for uint256", node.args[0])

        value = (2 ** 256 - 1) - value
        return vy_ast.Int.from_node(node, value=value)

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        return IRnode.from_list(["not", args[0]], typ=BaseType("uint256"))


class Shift(_SimpleBuiltinFunction):

    _id = "shift"
    _inputs = [("x", Uint256Definition()), ("_shift", SignedIntegerAbstractType())]
    _return_type = Uint256Definition()

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

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        if args[1].typ.is_literal:
            shift_abs = abs(args[1].value)
        else:
            shift_abs = ["sub", 0, "_s"]

        if version_check(begin="constantinople"):
            # TODO use convenience functions shl and shr in codegen/core.py
            if args[1].typ.is_literal:
                # optimization when SHL/SHR instructions are available shift distance is a literal
                value = args[1].value
                if value >= 0:
                    ir_node = ["shl", value, args[0]]
                else:
                    ir_node = ["shr", abs(value), args[0]]
                return IRnode.from_list(ir_node, typ=BaseType("uint256"))
            else:
                left_shift = ["shl", "_s", args[0]]
                right_shift = ["shr", shift_abs, args[0]]

        else:
            # If second argument is positive, left-shift so multiply by a power of two
            # If it is negative, divide by a power of two
            # node that if the abs of the second argument >= 256, then in the EVM
            # 2**(second arg) = 0, and multiplying OR dividing by 0 gives 0
            left_shift = ["mul", args[0], ["exp", 2, "_s"]]
            right_shift = ["div", args[0], ["exp", 2, shift_abs]]

        if not args[1].typ.is_literal:
            node_list = ["if", ["slt", "_s", 0], right_shift, left_shift]
        elif args[1].value >= 0:
            node_list = left_shift
        else:
            node_list = right_shift

        return IRnode.from_list(["with", "_s", args[1], node_list], typ=BaseType("uint256"))


class _AddMulMod(_SimpleBuiltinFunction):

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

    @validate_inputs
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


class PowMod256(_SimpleBuiltinFunction):
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


class Abs(_SimpleBuiltinFunction):
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


def get_create_forwarder_to_bytecode():
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


class CreateForwarderTo(_SimpleBuiltinFunction):

    _id = "create_forwarder_to"
    _inputs = [("target", AddressDefinition())]
    _kwargs = {"value": Optional("uint256", zero_value), "salt": Optional("bytes32", empty_value)}
    _return_type = AddressDefinition()

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        value = kwargs["value"]
        salt = kwargs["salt"]
        should_use_create2 = "salt" in [kwarg.arg for kwarg in expr.keywords]

        if context.is_constant():
            raise StateAccessViolation(
                f"Cannot make calls from {context.pp_constancy()}",
                expr,
            )
        placeholder = context.new_internal_variable(ByteArrayType(96))

        loader_evm, forwarder_pre_evm, forwarder_post_evm = get_create_forwarder_to_bytecode()
        # Adjust to 32-byte boundaries
        preamble_length = len(loader_evm) + len(forwarder_pre_evm)
        forwarder_preamble = bytes_to_int(
            loader_evm + forwarder_pre_evm + b"\x00" * (32 - preamble_length)
        )
        forwarder_post = bytes_to_int(forwarder_post_evm + b"\x00" * (32 - len(forwarder_post_evm)))

        if args[0].typ.is_literal:
            target_address = args[0].value * 2 ** 96
        elif version_check(begin="constantinople"):
            target_address = ["shl", 96, args[0]]
        else:
            target_address = ["mul", args[0], 2 ** 96]

        op = "create"
        op_args = [value, placeholder, preamble_length + 20 + len(forwarder_post_evm)]

        if should_use_create2:
            op = "create2"
            op_args.append(salt)

        return IRnode.from_list(
            [
                "seq",
                ["mstore", placeholder, forwarder_preamble],
                ["mstore", ["add", placeholder, preamble_length], target_address],
                ["mstore", ["add", placeholder, preamble_length + 20], forwarder_post],
                [op, *op_args],
            ],
            typ=BaseType("address"),
            add_gas_estimate=11000,
        )


class _UnsafeMath:

    # TODO add unsafe math for `decimal`s
    _inputs = [("a", IntegerAbstractType()), ("b", IntegerAbstractType())]

    def fetch_call_return(self, node):
        validate_call_args(node, 2)

        types_list = get_common_types(
            *node.args, filter_fn=lambda x: isinstance(x, IntegerAbstractType)
        )
        if not types_list:
            raise TypeMismatch(f"unsafe_{self.op} called on dislike types", node)

        return types_list.pop()

    @validate_inputs
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


class _MinMax:

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
        validate_call_args(node, 2)

        types_list = get_common_types(
            *node.args, filter_fn=lambda x: isinstance(x, NumericAbstractType)
        )
        if not types_list:
            raise TypeMismatch

        return types_list.pop()

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        def _can_compare_with_uint256(operand):
            if operand.typ.typ == "uint256":
                return True
            elif (
                operand.typ.typ == "int128"
                and operand.typ.is_literal
                and SizeLimits.in_bounds("uint256", operand.value)
            ):  # noqa: E501
                return True
            return False

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

            elif _can_compare_with_uint256(left) and _can_compare_with_uint256(right):
                o = ["select", [op, left, right], left, right]
                if right.typ.typ == "uint256":
                    otyp = right.typ
                else:
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


class Sqrt(_SimpleBuiltinFunction):

    _id = "sqrt"
    _inputs = [("d", DecimalDefinition())]
    _return_type = DecimalDefinition()

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        # TODO check out this import
        from vyper.builtin_functions.utils import generate_inline_function

        arg = args[0]
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
        # Generate inline IR.
        new_ctx, sqrt_ir = generate_inline_function(
            code=sqrt_code, variables=variables, memory_allocator=context.memory_allocator
        )
        return IRnode.from_list(
            [
                "seq",
                placeholder_copy,  # load x variable
                sqrt_ir,
                new_ctx.vars["z"].pos,
            ],
            typ=BaseType("decimal"),
            location=MEMORY,
        )


class Empty:

    _id = "empty"
    _inputs = [("typename", "*")]

    def fetch_call_return(self, node):
        validate_call_args(node, 1)
        type_ = get_type_from_annotation(node.args[0], DataLocation.MEMORY)
        return type_

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        output_type = context.parse_type(expr.args[0])
        return IRnode("~empty", typ=output_type)


class Print(_SimpleBuiltinFunction):
    _id = "print"
    _inputs = [("arg", "*")]

    _warned = False

    def fetch_call_return(self, node):
        if not self._warned:
            vyper_warn("`print` should only be used for debugging!\n" + node._annotated_source)
            self._warned = True

        validate_call_args(node, 1)
        return None

    @validate_inputs
    def build_IR(self, expr, args, kwargs, context):
        args = [Expr(arg, context).ir_node for arg in expr.args]
        args_tuple_t = TupleType([x.typ for x in args])
        args_as_tuple = IRnode.from_list(["multi"] + [x for x in args], typ=args_tuple_t)
        args_abi_t = args_tuple_t.abi_type
        # create a signature like "log(uint256)"
        sig = "log" + "(" + ",".join([arg.typ.abi_type.selector_name() for arg in args]) + ")"
        method_id = abi_method_id(sig)

        buflen = 32 + args_abi_t.size_bound()

        # 32 bytes extra space for the method id
        buf = context.new_internal_variable(get_type_for_exact_size(buflen))

        ret = ["seq"]
        ret.append(["mstore", buf, method_id])
        encode = abi_encode(buf + 32, args_as_tuple, context, buflen, returns_len=True)

        # debug address that tooling uses
        CONSOLE_ADDRESS = 0x000000000000000000636F6E736F6C652E6C6F67
        ret.append(["staticcall", "gas", CONSOLE_ADDRESS, buf + 28, encode, 0, 0])

        return IRnode.from_list(ret, annotation="print:" + sig)


class ABIEncode(_SimpleBuiltinFunction):
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

    @staticmethod
    # this should probably be a utility function
    def _exactly_one(xs):
        return len(set(xs)) == 1

    @staticmethod
    def _kwarg_dict(node):
        return {i.arg: i.value for i in node.keywords}

    def _ensure_tuple(self, node):
        # figure out if we need to encode single values as tuples
        ensure_tuple = self._kwarg_dict(node).get("ensure_tuple")
        if ensure_tuple is None:
            # default to True.
            return True

        elif not isinstance(ensure_tuple, vy_ast.NameConstant) or not isinstance(
            ensure_tuple.value, bool
        ):
            raise TypeMismatch(
                "The `ensure_tuple` parameter must be a static/literal boolean value", node
            )
        else:
            return ensure_tuple.value

    def _method_id(self, node):
        method_id = self._kwarg_dict(node).get("method_id")
        if method_id is None:
            return None

        def _check(cond):
            errmsg = (
                f"method_id must be a 4-byte hex literal or Bytes[4], "
                f'like method_id=0x12345678 or method_id=method_id("foo()") '
                f"\n{method_id}"
            )
            if not cond:
                raise TypeMismatch(errmsg)

        if isinstance(method_id, vy_ast.Bytes):
            _check(len(method_id.value) <= 4)
            return fourbytes_to_int(method_id.value)

        if isinstance(method_id, vy_ast.Hex):
            hexstr = method_id.value  # e.g. 0xdeadbeef
            _check(len(hexstr) // 2 - 1 <= 4)
            return int(hexstr, 16)

        _check(False)

    def fetch_call_return(self, node):
        # figure out the output type by converting
        # the types to ABI_Types and calling size_bound API
        arg_abi_types = []
        for arg in node.args:
            arg_t = get_exact_type_from_node(arg)
            arg_abi_types.append(arg_t.abi_type)

        # special case, no tuple
        if len(arg_abi_types) == 1 and not self._ensure_tuple(node):
            arg_abi_t = arg_abi_types[0]
        else:
            arg_abi_t = ABI_Tuple(arg_abi_types)

        maxlen = arg_abi_t.size_bound()

        if self._method_id(node) is not None:
            # the output includes 4 bytes for the method_id.
            maxlen += 4

        ret = BytesArrayDefinition()
        ret.set_length(maxlen)
        return ret

    def build_IR(self, expr, context):
        method_id = self._method_id(expr)

        args = [Expr(arg, context).ir_node for arg in expr.args]

        if len(args) < 1:
            raise StructureException("abi_encode expects at least one argument", expr)

        # figure out the required length for the output buffer
        if len(args) == 1 and not self._ensure_tuple(expr):
            # special case, no tuple
            encode_input = args[0]
        else:
            encode_input = ir_tuple_from_args(args)

        input_abi_t = encode_input.typ.abi_type
        maxlen = input_abi_t.size_bound()
        if method_id is not None:
            maxlen += 4

        buf_t = ByteArrayType(maxlen=maxlen)
        buf = context.new_internal_variable(buf_t)

        ret = ["seq"]
        if method_id is not None:
            # <32 bytes length> | <4 bytes method_id> | <everything else>
            # write the unaligned method_id first, then we will
            # overwrite the 28 bytes of zeros with the bytestring length
            ret += [["mstore", buf + 4, method_id]]
            # abi encode and grab length as stack item
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

        return IRnode.from_list(
            ret,
            location=MEMORY,
            typ=buf_t,
            annotation=f"abi_encode builtin ensure_tuple={self._ensure_tuple(expr)}",
        )


DISPATCH_TABLE = {
    "_abi_encode": ABIEncode(),
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
    "sqrt": Sqrt(),
    "shift": Shift(),
    "create_forwarder_to": CreateForwarderTo(),
    "min": Min(),
    "max": Max(),
    "empty": Empty(),
    "abs": Abs(),
}

STMT_DISPATCH_TABLE = {
    "send": Send(),
    "print": Print(),
    "selfdestruct": SelfDestruct(),
    "raw_call": RawCall(),
    "raw_log": RawLog(),
    "create_forwarder_to": CreateForwarderTo(),
}

BUILTIN_FUNCTIONS = {**STMT_DISPATCH_TABLE, **DISPATCH_TABLE}.keys()


def get_builtin_functions():
    return {**STMT_DISPATCH_TABLE, **DISPATCH_TABLE}
