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
)


@signature(('num', 'num256', 'bytes32', 'bytes'), 'str_literal')
def to_num(expr, args, kwargs, context):
    input = args[0]
    typ, len = get_type(input)
    if typ in ('num', 'num256', 'bytes32'):
        return LLLnode.from_list(
            ['clamp', ['mload', MemoryPositions.MINNUM], input, ['mload', MemoryPositions.MAXNUM]], typ=BaseType("num"), pos=getpos(expr)
        )
    else:
        return byte_array_to_num(input, expr, 'num')


@signature(('num_literal', 'num', 'bytes32'), 'str_literal')
def to_num256(expr, args, kwargs, context):
    input = args[0]
    typ, len = get_type(input)
    if isinstance(input, int):
        if not(0 <= input <= 2**256 - 1):
            raise InvalidLiteralException("Number out of range: {}".format(input))
        return LLLnode.from_list(input, typ=BaseType('num256'), pos=getpos(expr))
    elif isinstance(input, LLLnode) and typ in ('num', 'num_literal'):
        return LLLnode.from_list(['clampge', input, 0], typ=BaseType('num256'), pos=getpos(expr))
    elif isinstance(input, LLLnode) and typ in ('bytes32'):
        return LLLnode(value=input.value, args=input.args, typ=BaseType('num256'), pos=getpos(expr))
    else:
        raise InvalidLiteralException("Invalid input for num256: %r" % input, expr)


@signature('num', 'str_literal')
def to_decimal(expr, args, kwargs, context):
    input = args[0]
    return LLLnode.from_list(['mul', input, DECIMAL_DIVISOR], typ=BaseType('decimal', input.typ.unit, input.typ.positional),
                             pos=getpos(expr))


@signature(('num', 'num256', 'address', 'bytes'), 'str_literal')
def to_bytes32(expr, args, kwargs, context):
    input = args[0]
    typ, len = get_type(input)
    if typ == 'bytes':
        if len != 32:
            raise TypeMismatchException("Unable to convert bytes <= {} to bytes32".format(len))
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
    'num': to_num,
    'num256': to_num256,
    'decimal': to_decimal,
    'bytes32': to_bytes32,
}
