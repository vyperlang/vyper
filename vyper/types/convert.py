import ast
import warnings

from vyper.functions.signature import (
    signature
)
from vyper.parser.parser_utils import (
    LLLnode,
    getpos,
    byte_array_to_num
)
from vyper.exceptions import (
    InvalidLiteralException,
    TypeMismatchException,
    ParserException,
)
from vyper.types import (
    BaseType,
)
from vyper.types import (
    get_type,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    MemoryPositions,
    SizeLimits
)


@signature(('decimal', 'int128', 'uint256', 'bytes32', 'bytes'), '*')
def to_bool(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == 'bytes':
        if in_arg.typ.maxlen > 32:
            raise TypeMismatchException("Cannot convert bytes array of max length {} to int128".format(in_arg.value), expr)
        else:
            num = byte_array_to_num(in_arg, expr, 'uint256')
            return LLLnode.from_list(
                ['iszero', ['iszero', num]],
                typ=BaseType('bool'),
                pos=getpos(expr)
            )

    elif in_arg.typ.is_literal and in_arg.typ.typ == 'bool':
        raise InvalidLiteralException("Cannot convert to `bool` with boolean input literal.", expr)

    else:
        return LLLnode.from_list(
            ['iszero', ['iszero', in_arg]],
            typ=BaseType('bool', in_arg.typ.unit),
            pos=getpos(expr)
        )


@signature(('bytes32', 'bytes', 'uint256', 'bool'), '*')
def to_int128(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == 'bytes32':
        if in_arg.typ.is_literal and not SizeLimits.in_bounds('int128', in_arg.value):
            raise InvalidLiteralException("Number out of range: {}".format(in_arg.value), expr)
        return LLLnode.from_list(
            ['clamp', ['mload', MemoryPositions.MINNUM],
            in_arg, ['mload', MemoryPositions.MAXNUM]],
            typ=BaseType('int128', in_arg.typ.unit),
            pos=getpos(expr)
        )

    elif input_type == 'bytes':
        if in_arg.typ.maxlen > 32:
            raise TypeMismatchException("Cannot convert bytes array of max length {} to int128".format(in_arg.value), expr)
        return byte_array_to_num(in_arg, expr, 'int128')

    elif input_type == 'uint256':
        if in_arg.typ.is_literal and not SizeLimits.in_bounds('int128', in_arg.value):
            raise InvalidLiteralException("Number out of range: {}".format(in_arg.value), expr)
        return LLLnode.from_list(
            ['uclample', in_arg, ['mload', MemoryPositions.MAXNUM]],
            typ=BaseType('int128', in_arg.typ.unit),
            pos=getpos(expr)
        )

    elif input_type == 'bool':
        return LLLnode.from_list(
            in_arg,
            typ=BaseType('int128', in_arg.typ.unit),
            pos=getpos(expr)
        )

    else:
        raise InvalidLiteralException("Invalid input for int128: %r" % in_arg, expr)


@signature(('num_literal', 'int128', 'bytes32', 'bytes', 'address', 'bool'), '*')
def to_uint256(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)
    _unit = in_arg.typ.unit if input_type == 'int128' else None

    if isinstance(in_arg, int):
        if not SizeLimits.in_bounds('uint256', in_arg):
            raise InvalidLiteralException("Number out of range: {}".format(in_arg))
        return LLLnode.from_list(
            in_arg,
            typ=BaseType('uint256', _unit),
            pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type in ('int128', 'num_literal'):
        return LLLnode.from_list(
            ['clampge', in_arg, 0],
            typ=BaseType('uint256', _unit),
            pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type == 'bool':
        return LLLnode.from_list(
            in_arg,
            typ=BaseType('uint256'),
            pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type in ('bytes32', 'address'):
        return LLLnode(
            value=in_arg.value,
            args=in_arg.args,
            typ=BaseType('uint256'),
            pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type == 'bytes':
        if in_arg.typ.maxlen > 32:
            raise InvalidLiteralException("Cannot convert bytes array of max length {} to uint256".format(in_arg.value), expr)
        return byte_array_to_num(in_arg, expr, 'uint256')

    else:
        raise InvalidLiteralException("Invalid input for uint256: %r" % in_arg, expr)


@signature(('int128', 'uint256'), '*')
def to_decimal(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)
    _unit = in_arg.typ.unit
    _positional = in_arg.typ.positional

    if input_type == 'uint256':
        return LLLnode.from_list(
            ['uclample', ['mul', in_arg, DECIMAL_DIVISOR],
            ['mload', MemoryPositions.MAXDECIMAL]],
            typ=BaseType('decimal', _unit, _positional),
            pos=getpos(expr)
        )

    elif input_type == 'int128':
        return LLLnode.from_list(
            ['mul', in_arg, DECIMAL_DIVISOR],
            typ=BaseType('decimal', _unit, _positional),
            pos=getpos(expr)
        )

    else:
        raise InvalidLiteralException("Invalid input for decimal: %r" % in_arg, expr)


@signature(('int128', 'uint256', 'address', 'bytes', 'bool'), '*')
def to_bytes32(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _len = get_type(in_arg)

    if input_type == 'bytes':
        if _len > 32:
            raise TypeMismatchException("Unable to convert bytes[{}] to bytes32, max length is too large.".format(len))

        if in_arg.location == "memory":
            return LLLnode.from_list(
                ['mload', ['add', in_arg, 32]],
                typ=BaseType('bytes32')
            )
        elif in_arg.location == "storage":
            return LLLnode.from_list(
                ['sload', ['add', ['sha3_32', in_arg], 1]],
                typ=BaseType('bytes32')
            )

    else:
        return LLLnode(
            value=in_arg.value,
            args=in_arg.args,
            typ=BaseType('bytes32'),
            pos=getpos(expr)
        )


@signature(('bytes32'), '*')
def to_address(expr, args, kwargs, context):
    in_arg = args[0]

    return LLLnode(
        value=in_arg.value,
        args=in_arg.args,
        typ=BaseType('address'),
        pos=getpos(expr)
    )


def convert(expr, context):
    if isinstance(expr.args[1], ast.Str):
        warnings.warn(
            "String parameter has been removed (see VIP1026). "
            "Use a vyper type instead.",
            DeprecationWarning
        )

    if isinstance(expr.args[1], ast.Name):
        output_type = expr.args[1].id
    else:
        raise ParserException("Invalid conversion type, use valid Vyper type.", expr)

    if output_type in conversion_table:
        return conversion_table[output_type](expr, context)
    else:
        raise ParserException("Conversion to {} is invalid.".format(output_type), expr)


conversion_table = {
    'bool': to_bool,
    'int128': to_int128,
    'uint256': to_uint256,
    'decimal': to_decimal,
    'bytes32': to_bytes32,
    'address': to_address,
}
