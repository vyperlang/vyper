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


@signature(('uint256', 'bytes32', 'bytes'), '*')
def to_int128(expr, args, kwargs, context):
    in_node = args[0]
    typ, len = get_type(in_node)
    if typ in ('uint256', 'bytes32'):
        if in_node.typ.is_literal and not SizeLimits.in_bounds('int128', in_node.value):
            raise InvalidLiteralException("Number out of range: {}".format(in_node.value), expr)
        return LLLnode.from_list(
            ['clamp', ['mload', MemoryPositions.MINNUM], in_node,
                        ['mload', MemoryPositions.MAXNUM]], typ=BaseType('int128', in_node.typ.unit), pos=getpos(expr)
        )
    else:
        return byte_array_to_num(in_node, expr, 'int128')


@signature(('num_literal', 'int128', 'bytes32', 'address'), '*')
def to_uint256(expr, args, kwargs, context):
    in_node = args[0]
    input_type, len = get_type(in_node)

    if isinstance(in_node, int):
        if not SizeLimits.in_bounds('uint256', in_node):
            raise InvalidLiteralException("Number out of range: {}".format(in_node))
        _unit = in_node.typ.unit if input_type == 'int128' else None
        return LLLnode.from_list(in_node, typ=BaseType('uint256', _unit), pos=getpos(expr))

    elif isinstance(in_node, LLLnode) and input_type in ('int128', 'num_literal'):
        _unit = in_node.typ.unit if input_type == 'int128' else None
        return LLLnode.from_list(['clampge', in_node, 0], typ=BaseType('uint256', _unit), pos=getpos(expr))

    elif isinstance(in_node, LLLnode) and input_type in ('bytes32', 'address'):
        return LLLnode(value=in_node.value, args=in_node.args, typ=BaseType('uint256'), pos=getpos(expr))

    else:
        raise InvalidLiteralException("Invalid input for uint256: %r" % in_node, expr)


@signature(('int128', 'uint256'), '*')
def to_decimal(expr, args, kwargs, context):
    input = args[0]
    if input.typ.typ == 'uint256':
        return LLLnode.from_list(
            ['uclample', ['mul', input, DECIMAL_DIVISOR], ['mload', MemoryPositions.MAXDECIMAL]],
            typ=BaseType('decimal', input.typ.unit, input.typ.positional), pos=getpos(expr)
        )
    else:
        return LLLnode.from_list(
            ['mul', input, DECIMAL_DIVISOR],
            typ=BaseType('decimal', input.typ.unit, input.typ.positional),
            pos=getpos(expr)
        )


@signature(('int128', 'uint256', 'address', 'bytes'), '*')
def to_bytes32(expr, args, kwargs, context):
    in_arg = args[0]
    typ, _len = get_type(in_arg)

    if typ == 'bytes':

        if _len > 32:
            raise TypeMismatchException("Unable to convert bytes[{}] to bytes32, max length is too large.".format(len))

        if in_arg.location == "memory":
            return LLLnode.from_list(
            ['mload', ['add', in_arg, 32]], typ=BaseType('bytes32')
            )
        elif in_arg.location == "storage":
            return LLLnode.from_list(
                ['sload', ['add', ['sha3_32', in_arg], 1]], typ=BaseType('bytes32')
            )

    else:
        return LLLnode(value=in_arg.value, args=in_arg.args, typ=BaseType('bytes32'), pos=getpos(expr))


def convert(expr, context):

    if isinstance(expr.args[1], ast.Str):
        warnings.warn(
            "String parameter has been removed, see VIP1026). "
            "Use a vyper type instead.",
            DeprecationWarning
        )

    if isinstance(expr.args[1], ast.Name):
        output_type = expr.args[1].id
    else:
        raise ParserException("Invalid conversion type, use valid vyper type.", expr)

    if output_type in conversion_table:
        return conversion_table[output_type](expr, context)
    else:
        raise ParserException("Conversion to {} is invalid.".format(output_type), expr)


conversion_table = {
    'int128': to_int128,
    'uint256': to_uint256,
    'decimal': to_decimal,
    'bytes32': to_bytes32,
}
