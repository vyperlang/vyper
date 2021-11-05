import math
import warnings
from decimal import Decimal

from vyper import ast as vy_ast
from vyper.builtin_functions.signatures import signature
from vyper.evm.opcodes import version_check
from vyper.exceptions import InvalidLiteral, StructureException, TypeMismatch
from vyper.old_codegen.parser_utils import (
    LLLnode,
    add_ofst,
    clamp_basetype,
    get_bytearray_length,
    getpos,
    int_clamp,
    load_op,
    shr,
)
from vyper.old_codegen.types import BaseType, ByteArrayType, StringType, get_type
from vyper.utils import DECIMAL_DIVISOR, MemoryPositions, SizeLimits


def byte_array_to_num(
    arg,
    expr,  # TODO dead argument
    out_type,
    offset=32,  # TODO probably dead argument
):
    """
    Takes a <32 byte array as input, and outputs a number.
    """
    # the location of the bytestring
    bs_start = (
        LLLnode.from_list("bs_start", typ=arg.typ, location=arg.location, encoding=arg.encoding)
        if arg.is_complex_lll
        else arg
    )

    if arg.location == "storage":
        len_ = get_bytearray_length(bs_start)
        data = LLLnode.from_list(["sload", add_ofst(bs_start, 1)], typ=BaseType("int256"))
    else:
        op = load_op(arg.location)
        len_ = LLLnode.from_list([op, bs_start], typ=BaseType("int256"))
        data = LLLnode.from_list([op, add_ofst(bs_start, 32)], typ=BaseType("int256"))

    # converting a bytestring to a number:
    # bytestring is right-padded with zeroes, int is left-padded.
    # convert by shr the number of zero bytes (converted to bits)
    # e.g. "abcd000000000000" -> bitcast(000000000000abcd, output_type)
    bitcasted = LLLnode.from_list(shr("val", ["mul", 8, ["sub", 32, "len_"]]), typ=out_type)

    result = clamp_basetype(bitcasted)

    ret = ["with", "val", data, ["with", "len_", len_, result]]
    if arg.is_complex_lll:
        ret = ["with", "bs_start", arg, ret]
    return LLLnode.from_list(
        ret,
        typ=BaseType(out_type),
        annotation=f"__intrinsic__byte_array_to_num({out_type})",
    )


@signature(("decimal", "int128", "int256", "uint8", "uint256", "address", "bytes32", "Bytes"), "*")
def to_bool(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to bool",
                expr,
            )
        else:
            num = byte_array_to_num(in_arg, expr, "uint256")
            return LLLnode.from_list(
                ["iszero", ["iszero", num]], typ=BaseType("bool"), pos=getpos(expr)
            )

    else:
        return LLLnode.from_list(
            ["iszero", ["iszero", in_arg]], typ=BaseType("bool"), pos=getpos(expr)
        )


@signature(("decimal", "int128", "int256", "uint256", "bytes32", "Bytes"), "*")
def to_uint8(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to uint8",
                expr,
            )
        else:
            # uint8 clamp is already applied in byte_array_to_num
            in_arg = byte_array_to_num(in_arg, expr, "uint8")

    else:
        # cast to output type so clamp_basetype works
        in_arg = LLLnode.from_list(in_arg, typ="uint8")

    return LLLnode.from_list(clamp_basetype(in_arg), typ=BaseType("uint8"), pos=getpos(expr))


@signature(
    (
        "num_literal",
        "bool",
        "decimal",
        "uint8",
        "int256",
        "uint256",
        "address",
        "bytes32",
        "Bytes",
        "String",
    ),
    "*",
)
def to_int128(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "num_literal":
        if isinstance(in_arg, int):
            if not SizeLimits.in_bounds("int128", in_arg):
                raise InvalidLiteral(f"Number out of range: {in_arg}")
            return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))
        elif isinstance(in_arg, Decimal):
            if not SizeLimits.in_bounds("int128", math.trunc(in_arg)):
                raise InvalidLiteral(f"Number out of range: {math.trunc(in_arg)}")
            return LLLnode.from_list(math.trunc(in_arg), typ=BaseType("int128"), pos=getpos(expr))
        else:
            raise InvalidLiteral(f"Unknown numeric literal type: {in_arg}")

    elif input_type in ("bytes32", "int256"):
        if in_arg.typ.is_literal:
            if not SizeLimits.in_bounds("int128", in_arg.value):
                raise InvalidLiteral(f"Number out of range: {in_arg.value}", expr)
            else:
                return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))
        else:
            # cast to output type so clamp_basetype works
            in_arg = LLLnode.from_list(in_arg, typ="int128")
            return LLLnode.from_list(
                clamp_basetype(in_arg),
                typ=BaseType("int128"),
                pos=getpos(expr),
            )

    # CMC 20211020: what is the purpose of this .. it lops off 32 bits
    elif input_type == "address":
        return LLLnode.from_list(
            ["signextend", 15, ["and", in_arg, (SizeLimits.ADDRSIZE - 1)]],
            typ=BaseType("int128"),
            pos=getpos(expr),
        )

    elif input_type in ("String", "Bytes"):
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to int128",
                expr,
            )
        return byte_array_to_num(in_arg, expr, "int128")

    elif input_type == "uint256":
        if in_arg.typ.is_literal:
            if not SizeLimits.in_bounds("int128", in_arg.value):
                raise InvalidLiteral(f"Number out of range: {in_arg.value}", expr)
            else:
                return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))

        # !! do not use clamp_basetype. check that 0 <= input <= MAX_INT128.
        res = int_clamp(in_arg, 127, signed=False)
        return LLLnode.from_list(
            res,
            typ="int128",
            pos=getpos(expr),
        )

    elif input_type == "decimal":
        # cast to int128 so clamp_basetype works
        res = LLLnode.from_list(["sdiv", in_arg, DECIMAL_DIVISOR], typ="int128")
        return LLLnode.from_list(clamp_basetype(res), typ="int128", pos=getpos(expr))

    elif input_type in ("bool", "uint8"):
        # note: for int8, would need signextend
        return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))

    else:
        raise InvalidLiteral(f"Invalid input for int128: {in_arg}", expr)


@signature(
    ("num_literal", "int128", "int256", "uint8", "bytes32", "Bytes", "address", "bool", "decimal"),
    "*",
)
def to_uint256(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "num_literal":
        if isinstance(in_arg, int):
            if not SizeLimits.in_bounds("uint256", in_arg):
                raise InvalidLiteral(f"Number out of range: {in_arg}")
            return LLLnode.from_list(
                in_arg,
                typ=BaseType(
                    "uint256",
                ),
                pos=getpos(expr),
            )
        elif isinstance(in_arg, Decimal):
            if not SizeLimits.in_bounds("uint256", math.trunc(in_arg)):
                raise InvalidLiteral(f"Number out of range: {math.trunc(in_arg)}")
            return LLLnode.from_list(math.trunc(in_arg), typ=BaseType("uint256"), pos=getpos(expr))
        else:
            raise InvalidLiteral(f"Unknown numeric literal type: {in_arg}")

    elif isinstance(in_arg, LLLnode) and input_type in ("int128", "int256"):
        return LLLnode.from_list(["clampge", in_arg, 0], typ=BaseType("uint256"), pos=getpos(expr))

    elif isinstance(in_arg, LLLnode) and input_type == "decimal":
        return LLLnode.from_list(
            ["div", ["clampge", in_arg, 0], DECIMAL_DIVISOR],
            typ=BaseType("uint256"),
            pos=getpos(expr),
        )

    elif isinstance(in_arg, LLLnode) and input_type in ("bool", "uint8"):
        return LLLnode.from_list(in_arg, typ=BaseType("uint256"), pos=getpos(expr))

    elif isinstance(in_arg, LLLnode) and input_type in ("bytes32", "address"):
        return LLLnode(
            value=in_arg.value, args=in_arg.args, typ=BaseType("uint256"), pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise InvalidLiteral(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to uint256",
                expr,
            )
        return byte_array_to_num(in_arg, expr, "uint256")

    else:
        raise InvalidLiteral(f"Invalid input for uint256: {in_arg}", expr)


# TODO address support isn't added yet because of weirdness with int128 -> address
# conversions. in the next breaking release we should modify how address conversions work
# so it can make sense for many signed integer types. @iamdefinitelyahuman
@signature(
    ("num_literal", "int128", "uint8", "uint256", "bytes32", "Bytes", "String", "bool", "decimal"),
    "*",
)
def to_int256(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "num_literal":
        if isinstance(in_arg, int):
            if not SizeLimits.in_bounds("int256", in_arg):
                raise InvalidLiteral(f"Number out of range: {in_arg}")
            return LLLnode.from_list(
                in_arg,
                typ=BaseType(
                    "int256",
                ),
                pos=getpos(expr),
            )
        elif isinstance(in_arg, Decimal):
            if not SizeLimits.in_bounds("int256", math.trunc(in_arg)):
                raise InvalidLiteral(f"Number out of range: {math.trunc(in_arg)}")
            return LLLnode.from_list(math.trunc(in_arg), typ=BaseType("int256"), pos=getpos(expr))
        else:
            raise InvalidLiteral(f"Unknown numeric literal type: {in_arg}")

    elif isinstance(in_arg, LLLnode) and input_type == "int128":
        return LLLnode.from_list(in_arg, typ=BaseType("int256"), pos=getpos(expr))

    elif isinstance(in_arg, LLLnode) and input_type == "uint256":
        if version_check(begin="constantinople"):
            upper_bound = ["shl", 255, 1]
        else:
            upper_bound = -(2 ** 255)
        return LLLnode.from_list(
            ["uclamplt", in_arg, upper_bound], typ=BaseType("int256"), pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type == "decimal":
        return LLLnode.from_list(
            ["sdiv", in_arg, DECIMAL_DIVISOR],
            typ=BaseType("int256"),
            pos=getpos(expr),
        )

    elif isinstance(in_arg, LLLnode) and input_type in ("bool", "uint8"):
        return LLLnode.from_list(in_arg, typ=BaseType("int256"), pos=getpos(expr))

    elif isinstance(in_arg, LLLnode) and input_type in ("bytes32", "address"):
        return LLLnode(
            value=in_arg.value, args=in_arg.args, typ=BaseType("int256"), pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type in ("Bytes", "String"):
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to int256",
                expr,
            )
        return byte_array_to_num(in_arg, expr, "int256")

    else:
        raise InvalidLiteral(f"Invalid input for int256: {in_arg}", expr)


@signature(("bool", "int128", "int256", "uint8", "uint256", "bytes32", "Bytes", "address"), "*")
def to_decimal(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to decimal",
                expr,
            )
        # use byte_array_to_num(int128) because it is cheaper to clamp int128
        num = byte_array_to_num(in_arg, expr, "int128")
        return LLLnode.from_list(
            ["mul", num, DECIMAL_DIVISOR], typ=BaseType("decimal"), pos=getpos(expr)
        )

    else:
        if input_type == "uint256":
            if in_arg.typ.is_literal:
                if not SizeLimits.in_bounds("int128", (in_arg.value * DECIMAL_DIVISOR)):
                    raise InvalidLiteral(
                        f"Number out of range: {in_arg.value}",
                        expr,
                    )
                else:
                    return LLLnode.from_list(
                        ["mul", in_arg, DECIMAL_DIVISOR], typ=BaseType("decimal"), pos=getpos(expr)
                    )
            else:
                return LLLnode.from_list(
                    [
                        "uclample",
                        ["mul", in_arg, DECIMAL_DIVISOR],
                        ["mload", MemoryPositions.MAXDECIMAL],
                    ],
                    typ=BaseType("decimal"),
                    pos=getpos(expr),
                )

        elif input_type == "address":
            return LLLnode.from_list(
                [
                    "mul",
                    ["signextend", 15, ["and", in_arg, (SizeLimits.ADDRSIZE - 1)]],
                    DECIMAL_DIVISOR,
                ],
                typ=BaseType("decimal"),
                pos=getpos(expr),
            )

        elif input_type == "bytes32":
            if in_arg.typ.is_literal:
                if not SizeLimits.in_bounds("int128", (in_arg.value * DECIMAL_DIVISOR)):
                    raise InvalidLiteral(
                        f"Number out of range: {in_arg.value}",
                        expr,
                    )
                else:
                    return LLLnode.from_list(
                        ["mul", in_arg, DECIMAL_DIVISOR], typ=BaseType("decimal"), pos=getpos(expr)
                    )
            else:
                return LLLnode.from_list(
                    [
                        "clamp",
                        ["mload", MemoryPositions.MINDECIMAL],
                        ["mul", in_arg, DECIMAL_DIVISOR],
                        ["mload", MemoryPositions.MAXDECIMAL],
                    ],
                    typ=BaseType("decimal"),
                    pos=getpos(expr),
                )

        elif input_type == "int256":
            # cast in_arg so clamp_basetype works
            in_arg = LLLnode.from_list(in_arg, typ="int128")
            return LLLnode.from_list(
                ["mul", clamp_basetype(in_arg), DECIMAL_DIVISOR],
                typ=BaseType("decimal"),
                pos=getpos(expr),
            )

        elif input_type in ("uint8", "int128", "bool"):
            return LLLnode.from_list(
                ["mul", in_arg, DECIMAL_DIVISOR], typ=BaseType("decimal"), pos=getpos(expr)
            )

        else:
            raise InvalidLiteral(f"Invalid input for decimal: {in_arg}", expr)


@signature(("int128", "int256", "uint8", "uint256", "address", "Bytes", "bool", "decimal"), "*")
def to_bytes32(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _len = get_type(in_arg)

    if input_type == "Bytes":
        if _len > 32:
            raise TypeMismatch(
                f"Unable to convert bytes[{_len}] to bytes32, max length is too " "large."
            )

        if in_arg.location == "storage":
            return LLLnode.from_list(["sload", ["add", in_arg, 1]], typ=BaseType("bytes32"))
        else:
            op = load_op(in_arg.location)
            return LLLnode.from_list([op, ["add", in_arg, 32]], typ=BaseType("bytes32"))

    else:
        return LLLnode(
            value=in_arg.value, args=in_arg.args, typ=BaseType("bytes32"), pos=getpos(expr)
        )


@signature(("bytes32", "uint256"), "*")
def to_address(expr, args, kwargs, context):
    # cast to output type so clamp_basetype works
    lll_node = LLLnode.from_list(args[0], typ="address")
    return LLLnode.from_list(clamp_basetype(lll_node), typ=BaseType("address"), pos=getpos(expr))


def _to_bytelike(expr, args, kwargs, context, bytetype):
    if bytetype == "String":
        ReturnType = StringType
    elif bytetype == "Bytes":
        ReturnType = ByteArrayType
    else:
        raise TypeMismatch(f"Invalid {bytetype} supplied")

    in_arg = args[0]
    if in_arg.typ.maxlen > args[1].slice.value.n:
        raise TypeMismatch(
            f"Cannot convert as input {bytetype} are larger than max length",
            expr,
        )

    return LLLnode(
        value=in_arg.value,
        args=in_arg.args,
        typ=ReturnType(in_arg.typ.maxlen),
        pos=getpos(expr),
        location=in_arg.location,
    )


@signature(("Bytes"), "*")
def to_string(expr, args, kwargs, context):
    return _to_bytelike(expr, args, kwargs, context, bytetype="String")


@signature(("String"), "*")
def to_bytes(expr, args, kwargs, context):
    return _to_bytelike(expr, args, kwargs, context, bytetype="Bytes")


def convert(expr, context):
    if len(expr.args) != 2:
        raise StructureException("The convert function expects two parameters.", expr)
    if isinstance(expr.args[1], vy_ast.Str):
        warnings.warn(
            "String parameter has been removed (see VIP1026). " "Use a vyper type instead.",
            DeprecationWarning,
        )

    if isinstance(expr.args[1], vy_ast.Name):
        output_type = expr.args[1].id
    elif isinstance(expr.args[1], (vy_ast.Subscript)) and isinstance(
        expr.args[1].value, (vy_ast.Name)
    ):
        output_type = expr.args[1].value.id
    else:
        raise StructureException("Invalid conversion type, use valid Vyper type.", expr)

    if output_type in CONVERSION_TABLE:
        return CONVERSION_TABLE[output_type](expr, context)
    else:
        raise StructureException(f"Conversion to {output_type} is invalid.", expr)


CONVERSION_TABLE = {
    "bool": to_bool,
    "int128": to_int128,
    "int256": to_int256,
    "uint8": to_uint8,
    "uint256": to_uint256,
    "decimal": to_decimal,
    "bytes32": to_bytes32,
    "address": to_address,
    "String": to_string,
    "Bytes": to_bytes,
}
