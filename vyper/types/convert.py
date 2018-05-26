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


@signature(('int128', 'uint256', 'bytes32', 'bytes'), 'str_literal')
def to_int128(expr, args, kwargs, context):
    in_node = args[0]
    typ, len = get_type(in_node)
    if typ in ('int128', 'uint256', 'bytes32'):
        if in_node.typ.is_literal and not SizeLimits.in_bounds('int128', in_node.value):
            raise InvalidLiteralException("Number out of range: {}".format(in_node.value), expr)
        return LLLnode.from_list(
            ['clamp', ['mload', MemoryPositions.MINNUM], in_node, ['mload', MemoryPositions.MAXNUM]], typ=BaseType('int128'), pos=getpos(expr)
        )
    else:
        return byte_array_to_num(in_node, expr, 'int128')


@signature(('num_literal', 'int128', 'bytes32'), 'str_literal')
def to_uint256(expr, args, kwargs, context):
    input = args[0]
    typ, len = get_type(input)
    if isinstance(input, int):
        if not(0 <= input <= 2**256 - 1):
            raise InvalidLiteralException("Number out of range: {}".format(input))
        return LLLnode.from_list(input, typ=BaseType('uint256'), pos=getpos(expr))
    elif isinstance(input, LLLnode) and typ in ('int128', 'num_literal'):
        return LLLnode.from_list(['clampge', input, 0], typ=BaseType('uint256'), pos=getpos(expr))
    elif isinstance(input, LLLnode) and typ in ('bytes32'):
        return LLLnode(value=input.value, args=input.args, typ=BaseType('uint256'), pos=getpos(expr))
    else:
        raise InvalidLiteralException("Invalid input for uint256: %r" % input, expr)


@signature('int128', 'str_literal')
def to_decimal(expr, args, kwargs, context):
    input = args[0]
    return LLLnode.from_list(['mul', input, DECIMAL_DIVISOR], typ=BaseType('decimal', input.typ.unit, input.typ.positional),
                             pos=getpos(expr))


@signature(('int128', 'uint256', 'address', 'bytes'), 'str_literal')
def to_bytes32(expr, args, kwargs, context):
    input = args[0]
    typ, len = get_type(input)
    if typ == 'bytes':
        if len != 32:
            raise TypeMismatchException("Unable to convert bytes[{}] to bytes32".format(len))
        if input.location == "memory":
            return LLLnode.from_list(
            ['mload', ['add', input, 32]], typ=BaseType('bytes32')
            )
        elif input.location == "storage":
            return LLLnode.from_list(
                ['sload', ['add', ['sha3_32', input], 1]], typ=BaseType('bytes32')
            )
    else:
        return LLLnode(value=input.value, args=input.args, typ=BaseType('bytes32'), pos=getpos(expr))


def convert(expr, context):
    output_type = expr.args[1].s
    if output_type in conversion_table:
        return conversion_table[output_type](expr, context)
    else:
        raise Exception("Conversion to {} is invalid.".format(output_type))


conversion_table = {
    'int128': to_int128,
    'uint256': to_uint256,
    'decimal': to_decimal,
    'bytes32': to_bytes32,
}
