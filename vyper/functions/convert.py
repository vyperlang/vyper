import math
import warnings
from decimal import Decimal

from vyper import ast as vy_ast
from vyper.exceptions import InvalidLiteral, StructureException, TypeMismatch
from vyper.functions.signatures import signature
from vyper.parser.parser_utils import LLLnode, byte_array_to_num, getpos
from vyper.types import BaseType, ByteArrayType, StringType, get_type
from vyper.utils import DECIMAL_DIVISOR, MemoryPositions, SizeLimits


@signature(("decimal", "int128", "uint256", "address", "bytes32", "Bytes"), "*")
def to_bool(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to bool", expr,
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


@signature(
    ("num_literal", "bool", "decimal", "uint256", "address", "bytes32", "Bytes", "String"), "*"
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

    elif input_type == "bytes32":
        if in_arg.typ.is_literal:
            if not SizeLimits.in_bounds("int128", in_arg.value):
                raise InvalidLiteral(f"Number out of range: {in_arg.value}", expr)
            else:
                return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))
        else:
            return LLLnode.from_list(
                [
                    "clamp",
                    ["mload", MemoryPositions.MINNUM],
                    in_arg,
                    ["mload", MemoryPositions.MAXNUM],
                ],
                typ=BaseType("int128"),
                pos=getpos(expr),
            )

    elif input_type == "address":
        return LLLnode.from_list(
            ["signextend", 15, ["and", in_arg, (SizeLimits.ADDRSIZE - 1)]],
            typ=BaseType("int128"),
            pos=getpos(expr),
        )

    elif input_type in ("String", "Bytes"):
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to int128", expr,
            )
        return byte_array_to_num(in_arg, expr, "int128")

    elif input_type == "uint256":
        if in_arg.typ.is_literal:
            if not SizeLimits.in_bounds("int128", in_arg.value):
                raise InvalidLiteral(f"Number out of range: {in_arg.value}", expr)
            else:
                return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))

        else:
            return LLLnode.from_list(
                ["uclample", in_arg, ["mload", MemoryPositions.MAXNUM]],
                typ=BaseType("int128"),
                pos=getpos(expr),
            )

    elif input_type == "decimal":
        return LLLnode.from_list(
            [
                "clamp",
                ["mload", MemoryPositions.MINNUM],
                ["sdiv", in_arg, DECIMAL_DIVISOR],
                ["mload", MemoryPositions.MAXNUM],
            ],
            typ=BaseType("int128"),
            pos=getpos(expr),
        )

    elif input_type == "bool":
        return LLLnode.from_list(in_arg, typ=BaseType("int128"), pos=getpos(expr))

    else:
        raise InvalidLiteral(f"Invalid input for int128: {in_arg}", expr)


@signature(("num_literal", "int128", "bytes32", "Bytes", "address", "bool", "decimal"), "*")
def to_uint256(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "num_literal":
        if isinstance(in_arg, int):
            if not SizeLimits.in_bounds("uint256", in_arg):
                raise InvalidLiteral(f"Number out of range: {in_arg}")
            return LLLnode.from_list(in_arg, typ=BaseType("uint256",), pos=getpos(expr))
        elif isinstance(in_arg, Decimal):
            if not SizeLimits.in_bounds("uint256", math.trunc(in_arg)):
                raise InvalidLiteral(f"Number out of range: {math.trunc(in_arg)}")
            return LLLnode.from_list(math.trunc(in_arg), typ=BaseType("uint256"), pos=getpos(expr))
        else:
            raise InvalidLiteral(f"Unknown numeric literal type: {in_arg}")

    elif isinstance(in_arg, LLLnode) and input_type == "int128":
        return LLLnode.from_list(["clampge", in_arg, 0], typ=BaseType("uint256"), pos=getpos(expr))

    elif isinstance(in_arg, LLLnode) and input_type == "decimal":
        return LLLnode.from_list(
            ["div", ["clampge", in_arg, 0], DECIMAL_DIVISOR],
            typ=BaseType("uint256"),
            pos=getpos(expr),
        )

    elif isinstance(in_arg, LLLnode) and input_type == "bool":
        return LLLnode.from_list(in_arg, typ=BaseType("uint256"), pos=getpos(expr))

    elif isinstance(in_arg, LLLnode) and input_type in ("bytes32", "address"):
        return LLLnode(
            value=in_arg.value, args=in_arg.args, typ=BaseType("uint256"), pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise InvalidLiteral(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to uint256", expr,
            )
        return byte_array_to_num(in_arg, expr, "uint256")

    else:
        raise InvalidLiteral(f"Invalid input for uint256: {in_arg}", expr)


@signature(("bool", "int128", "uint256", "bytes32", "Bytes", "address"), "*")
def to_decimal(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == "Bytes":
        if in_arg.typ.maxlen > 32:
            raise TypeMismatch(
                f"Cannot convert bytes array of max length {in_arg.typ.maxlen} to decimal", expr,
            )
        num = byte_array_to_num(in_arg, expr, "int128")
        return LLLnode.from_list(
            ["mul", num, DECIMAL_DIVISOR], typ=BaseType("decimal"), pos=getpos(expr)
        )

    else:
        if input_type == "uint256":
            if in_arg.typ.is_literal:
                if not SizeLimits.in_bounds("int128", (in_arg.value * DECIMAL_DIVISOR)):
                    raise InvalidLiteral(
                        f"Number out of range: {in_arg.value}", expr,
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
                        f"Number out of range: {in_arg.value}", expr,
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

        elif input_type in ("int128", "bool"):
            return LLLnode.from_list(
                ["mul", in_arg, DECIMAL_DIVISOR], typ=BaseType("decimal"), pos=getpos(expr)
            )

        else:
            raise InvalidLiteral(f"Invalid input for decimal: {in_arg}", expr)


@signature(("int128", "uint256", "address", "Bytes", "bool", "decimal"), "*")
def to_bytes32(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _len = get_type(in_arg)

    if input_type == "Bytes":
        if _len > 32:
            raise TypeMismatch(
                f"Unable to convert bytes[{_len}] to bytes32, max length is too " "large."
            )

        if in_arg.location == "memory":
            return LLLnode.from_list(["mload", ["add", in_arg, 32]], typ=BaseType("bytes32"))
        elif in_arg.location == "storage":
            return LLLnode.from_list(
                ["sload", ["add", ["sha3_32", in_arg], 1]], typ=BaseType("bytes32")
            )

    else:
        return LLLnode(
            value=in_arg.value, args=in_arg.args, typ=BaseType("bytes32"), pos=getpos(expr)
        )


@signature(("bytes32"), "*")
def to_address(expr, args, kwargs, context):
    in_arg = args[0]

    return LLLnode(value=in_arg.value, args=in_arg.args, typ=BaseType("address"), pos=getpos(expr))


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
            f"Cannot convert as input {bytetype} are larger than max length", expr,
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
    "uint256": to_uint256,
    "decimal": to_decimal,
    "bytes32": to_bytes32,
    "address": to_address,
    "String": to_string,
    "Bytes": to_bytes,
}
