import math
import warnings

from vyper import ast
from vyper.exceptions import (
    InvalidLiteralException,
    ParserException,
    TypeMismatchException,
)
from vyper.functions.signatures import (
    signature,
)
from vyper.parser.parser_utils import (
    LLLnode,
    byte_array_to_num,
    getpos,
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    StringType,
    get_type,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    MemoryPositions,
    SizeLimits,
)


@signature(('decimal', 'int128', 'uint256', 'bytes32', 'bytes'), '*')
def to_bool(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == 'bytes':
        if in_arg.typ.maxlen > 32:
            raise TypeMismatchException(
                "Cannot convert bytes array of max length {} to bool".format(
                    in_arg.value,
                ),
                expr,
            )
        else:
            num = byte_array_to_num(in_arg, expr, 'uint256')
            return LLLnode.from_list(
                ['iszero', ['iszero', num]],
                typ=BaseType('bool'),
                pos=getpos(expr)
            )

    else:
        return LLLnode.from_list(
            ['iszero', ['iszero', in_arg]],
            typ=BaseType('bool', in_arg.typ.unit),
            pos=getpos(expr)
        )


@signature(('num_literal', 'bool', 'decimal', 'uint256', 'bytes32', 'bytes', 'string'), '*')
def to_int128(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)
    _unit = in_arg.typ.unit if input_type in ('uint256', 'decimal') else None

    if input_type == 'num_literal':
        if isinstance(in_arg, int):
            if not SizeLimits.in_bounds('int128', in_arg):
                raise InvalidLiteralException("Number out of range: {}".format(in_arg))
            return LLLnode.from_list(
                in_arg,
                typ=BaseType('int128', _unit),
                pos=getpos(expr)
            )
        elif isinstance(in_arg, float):
            if not SizeLimits.in_bounds('int128', math.trunc(in_arg)):
                raise InvalidLiteralException("Number out of range: {}".format(math.trunc(in_arg)))
            return LLLnode.from_list(
                math.trunc(in_arg),
                typ=BaseType('int128', _unit),
                pos=getpos(expr)
            )
        else:
            raise InvalidLiteralException("Unknown numeric literal type: {}".fornat(in_arg))

    elif input_type == 'bytes32':
        if in_arg.typ.is_literal:
            if not SizeLimits.in_bounds('int128', in_arg.value):
                raise InvalidLiteralException("Number out of range: {}".format(in_arg.value), expr)
            else:
                return LLLnode.from_list(
                    in_arg,
                    typ=BaseType('int128', _unit),
                    pos=getpos(expr)
                )
        else:
            return LLLnode.from_list(
                [
                    'clamp',
                    ['mload', MemoryPositions.MINNUM],
                    in_arg,
                    ['mload', MemoryPositions.MAXNUM],
                ],
                typ=BaseType('int128', _unit),
                pos=getpos(expr)
            )

    elif input_type in ('string', 'bytes'):
        if in_arg.typ.maxlen > 32:
            raise TypeMismatchException(
                "Cannot convert bytes array of max length {} to int128".format(in_arg.value),
                expr,
            )
        return byte_array_to_num(in_arg, expr, 'int128')

    elif input_type == 'uint256':
        if in_arg.typ.is_literal:
            if not SizeLimits.in_bounds('int128', in_arg.value):
                raise InvalidLiteralException("Number out of range: {}".format(in_arg.value), expr)
            else:
                return LLLnode.from_list(
                    in_arg,
                    typ=BaseType('int128', _unit),
                    pos=getpos(expr)
                )

        else:
            return LLLnode.from_list(
                ['uclample', in_arg, ['mload', MemoryPositions.MAXNUM]],
                typ=BaseType('int128', _unit),
                pos=getpos(expr)
            )

    elif input_type == 'decimal':
        return LLLnode.from_list(
            [
                'clamp',
                ['mload', MemoryPositions.MINNUM],
                ['sdiv', in_arg, DECIMAL_DIVISOR],
                ['mload', MemoryPositions.MAXNUM],
            ],
            typ=BaseType('int128', _unit),
            pos=getpos(expr)
        )

    elif input_type == 'bool':
        return LLLnode.from_list(
            in_arg,
            typ=BaseType('int128', _unit),
            pos=getpos(expr)
        )

    else:
        raise InvalidLiteralException("Invalid input for int128: %r" % in_arg, expr)


@signature(('num_literal', 'int128', 'bytes32', 'bytes', 'address', 'bool', 'decimal'), '*')
def to_uint256(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)
    _unit = in_arg.typ.unit if input_type in ('int128', 'decimal') else None

    if input_type == 'num_literal':
        if isinstance(in_arg, int):
            if not SizeLimits.in_bounds('uint256', in_arg):
                raise InvalidLiteralException("Number out of range: {}".format(in_arg))
            return LLLnode.from_list(
                in_arg,
                typ=BaseType('uint256', _unit),
                pos=getpos(expr)
            )
        elif isinstance(in_arg, float):
            if not SizeLimits.in_bounds('uint256', math.trunc(in_arg)):
                raise InvalidLiteralException("Number out of range: {}".format(math.trunc(in_arg)))
            return LLLnode.from_list(
                math.trunc(in_arg),
                typ=BaseType('uint256', _unit),
                pos=getpos(expr)
            )
        else:
            raise InvalidLiteralException("Unknown numeric literal type: {}".fornat(in_arg))

    elif isinstance(in_arg, LLLnode) and input_type == 'int128':
        return LLLnode.from_list(
            ['clampge', in_arg, 0],
            typ=BaseType('uint256', _unit),
            pos=getpos(expr)
        )

    elif isinstance(in_arg, LLLnode) and input_type == 'decimal':
        return LLLnode.from_list(
            ['div', ['clampge', in_arg, 0], DECIMAL_DIVISOR],
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
            raise InvalidLiteralException(
                "Cannot convert bytes array of max length {} to uint256".format(in_arg.value),
                expr,
            )
        return byte_array_to_num(in_arg, expr, 'uint256')

    else:
        raise InvalidLiteralException("Invalid input for uint256: %r" % in_arg, expr)


@signature(('bool', 'int128', 'uint256', 'bytes32', 'bytes'), '*')
def to_decimal(expr, args, kwargs, context):
    in_arg = args[0]
    input_type, _ = get_type(in_arg)

    if input_type == 'bytes':
        if in_arg.typ.maxlen > 32:
            raise TypeMismatchException(
                "Cannot convert bytes array of max length {} to decimal".format(in_arg.value),
                expr,
            )
        num = byte_array_to_num(in_arg, expr, 'int128')
        return LLLnode.from_list(
            ['mul', num, DECIMAL_DIVISOR],
            typ=BaseType('decimal'),
            pos=getpos(expr)
        )

    else:
        _unit = in_arg.typ.unit
        _positional = in_arg.typ.positional

        if input_type == 'uint256':
            if in_arg.typ.is_literal:
                if not SizeLimits.in_bounds('int128', (in_arg.value * DECIMAL_DIVISOR)):
                    raise InvalidLiteralException(
                        "Number out of range: {}".format(in_arg.value),
                        expr,
                    )
                else:
                    return LLLnode.from_list(
                        ['mul', in_arg, DECIMAL_DIVISOR],
                        typ=BaseType('decimal', _unit, _positional),
                        pos=getpos(expr)
                    )
            else:
                return LLLnode.from_list(
                    [
                        'uclample',
                        ['mul', in_arg, DECIMAL_DIVISOR],
                        ['mload', MemoryPositions.MAXDECIMAL]
                    ],
                    typ=BaseType('decimal', _unit, _positional),
                    pos=getpos(expr)
                )

        elif input_type == 'bytes32':
            if in_arg.typ.is_literal:
                if not SizeLimits.in_bounds('int128', (in_arg.value * DECIMAL_DIVISOR)):
                    raise InvalidLiteralException(
                        "Number out of range: {}".format(in_arg.value),
                        expr,
                    )
                else:
                    return LLLnode.from_list(
                        ['mul', in_arg, DECIMAL_DIVISOR],
                        typ=BaseType('decimal', _unit, _positional),
                        pos=getpos(expr)
                    )
            else:
                return LLLnode.from_list(
                    [
                        'clamp',
                        ['mload', MemoryPositions.MINDECIMAL],
                        ['mul', in_arg, DECIMAL_DIVISOR],
                        ['mload', MemoryPositions.MAXDECIMAL],
                    ],
                    typ=BaseType('decimal', _unit, _positional),
                    pos=getpos(expr)
                )

        elif input_type in ('int128', 'bool'):
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
            raise TypeMismatchException((
                "Unable to convert bytes[{}] to bytes32, max length is too "
                "large."
            ).format(len))

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


def _to_bytelike(expr, args, kwargs, context, bytetype):
    if bytetype == 'string':
        ReturnType = StringType
    elif bytetype == 'bytes':
        ReturnType = ByteArrayType
    else:
        raise TypeMismatchException(f'Invalid {bytetype} supplied')

    in_arg = args[0]
    if in_arg.typ.maxlen > args[1].slice.value.n:
        raise TypeMismatchException(
            f'Cannot convert as input {bytetype} are larger than max length',
            expr,
        )

    return LLLnode(
        value=in_arg.value,
        args=in_arg.args,
        typ=ReturnType(in_arg.typ.maxlen),
        pos=getpos(expr),
        location=in_arg.location
    )


@signature(('bytes'), '*')
def to_string(expr, args, kwargs, context):
    return _to_bytelike(expr, args, kwargs, context, bytetype='string')


@signature(('string'), '*')
def to_bytes(expr, args, kwargs, context):
    return _to_bytelike(expr, args, kwargs, context, bytetype='bytes')


def convert(expr, context):
    if len(expr.args) != 2:
        raise ParserException('The convert function expects two parameters.', expr)
    if isinstance(expr.args[1], ast.Str):
        warnings.warn(
            "String parameter has been removed (see VIP1026). "
            "Use a vyper type instead.",
            DeprecationWarning
        )

    if isinstance(expr.args[1], ast.Name):
        output_type = expr.args[1].id
    elif isinstance(expr.args[1], (ast.Subscript)) and isinstance(expr.args[1].value, (ast.Name)):
        output_type = expr.args[1].value.id
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
    'string': to_string,
    'bytes': to_bytes
}
