import ast

from .exceptions import (
    ConstancyViolationException,
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
)
from viper.parser.parser_utils import (
    byte_array_to_num,
    LLLnode,
    get_length,
    get_number_as_fraction,
    get_original_if_0x_prefixed,
    getpos,
    make_byte_array_copier,
    make_byte_slice_copier,
    add_variable_offset,
    unwrap_location
)
from viper.parser.expr import (
    Expr,
)
from .types import (
    BaseType,
    ByteArrayType,
    TupleType,
    ListType
)
from .types import (
    are_units_compatible,
    parse_type,
    is_base_type,
    get_size_of_type,
)
from viper.utils import (
    MemoryPositions,
    DECIMAL_DIVISOR,
    RLP_DECODER_ADDRESS
)
from .utils import (
    bytes_to_int,
    fourbytes_to_int,
    sha3,
)


class Optional(object):
    def __init__(self, typ, default):
        self.typ = typ
        self.default = default


def process_arg(index, arg, expected_arg_typelist, function_name, context):
    if isinstance(expected_arg_typelist, Optional):
        expected_arg_typelist = expected_arg_typelist.typ
    if not isinstance(expected_arg_typelist, tuple):
        expected_arg_typelist = (expected_arg_typelist, )
    vsub = None
    for expected_arg in expected_arg_typelist:
        if expected_arg == 'num_literal':
            if isinstance(arg, ast.Num) and get_original_if_0x_prefixed(arg, context) is None:
                return arg.n
        elif expected_arg == 'str_literal':
            if isinstance(arg, ast.Str) and get_original_if_0x_prefixed(arg, context) is None:
                bytez = b''
                for c in arg.s:
                    if ord(c) >= 256:
                        raise InvalidLiteralException("Cannot insert special character %r into byte array" % c, arg)
                    bytez += bytes([ord(c)])
                return bytez
        elif expected_arg == 'name_literal':
            if isinstance(arg, ast.Name):
                return arg.id
        elif expected_arg == '*':
            return arg
        elif expected_arg == 'bytes':
            sub = Expr(arg, context).lll_node
            if isinstance(sub.typ, ByteArrayType):
                return sub
        else:
            # Does not work for unit-endowed types inside compound types, eg. timestamp[2]
            parsed_expected_type = parse_type(ast.parse(expected_arg).body[0].value, 'memory')
            if isinstance(parsed_expected_type, BaseType):
                vsub = vsub or Expr.parse_value_expr(arg, context)
                if is_base_type(vsub.typ, expected_arg):
                    return vsub
            else:
                vsub = vsub or Expr(arg, context).lll_node
                if vsub.typ == parsed_expected_type:
                    return Expr(arg, context).lll_node
    if len(expected_arg_typelist) == 1:
        raise TypeMismatchException("Expecting %s for argument %r of %s" %
                                    (expected_arg, index, function_name), arg)
    else:
        raise TypeMismatchException("Expecting one of %r for argument %r of %s" %
                                    (expected_arg_typelist, index, function_name), arg)


def signature(*argz, **kwargz):
    def decorator(f):
        def g(element, context):
            function_name = element.func.id
            if len(element.args) > len(argz):
                raise StructureException("Expected %d arguments for %s, got %d" %
                                         (len(argz), function_name, len(element.args)),
                                         element)
            subs = []
            for i, expected_arg in enumerate(argz):
                if len(element.args) > i:
                    subs.append(process_arg(i + 1, element.args[i], expected_arg, function_name, context))
                elif isinstance(expected_arg, Optional):
                    subs.append(expected_arg.default)
                else:
                    raise StructureException(
                        "Not enough arguments for function: {}".format(element.func.id),
                        element
                    )
            kwsubs = {}
            element_kw = {k.arg: k.value for k in element.keywords}
            for k, expected_arg in kwargz.items():
                if k not in element_kw:
                    if isinstance(expected_arg, Optional):
                        kwsubs[k] = expected_arg.default
                    else:
                        raise StructureException("Function %s requires argument %s" %
                                                 (function_name, k), element)
                else:
                    kwsubs[k] = process_arg(k, element_kw[k], expected_arg, function_name, context)
            for k, arg in element_kw.items():
                if k not in kwargz:
                    raise StructureException("Unexpected argument: %s"
                                             % k, element)
            return f(element, subs, kwsubs, context)
        return g
    return decorator


def enforce_units(typ, obj, expected):
    if not are_units_compatible(typ, expected):
        raise TypeMismatchException("Invalid units", obj)


def get_keyword(expr, keyword):
    for kw in expr.keywords:
        if kw.arg == keyword:
            return kw.value
    raise Exception("Keyword %s not found" % keyword)


@signature('decimal')
def floor(expr, args, kwargs, context):
    return LLLnode.from_list(
        ['sdiv', args[0], DECIMAL_DIVISOR], typ=BaseType('num', args[0].typ.unit, args[0].typ.positional),
        pos=getpos(expr)
    )


@signature(('num', 'decimal'))
def decimal(expr, args, kwargs, context):
    if args[0].typ.typ == 'decimal':
        return args[0]
    else:
        return LLLnode.from_list(
            ['mul', args[0], DECIMAL_DIVISOR], typ=BaseType('decimal', args[0].typ.unit, args[0].typ.positional),
            pos=getpos(expr)
        )


@signature(('num', 'decimal'))
def as_unitless_number(expr, args, kwargs, context):
    return LLLnode(value=args[0].value, args=args[0].args, typ=BaseType(args[0].typ.typ, {}), pos=getpos(expr))


@signature(('num', 'bytes32', 'num256'))
def as_num128(expr, args, kwargs, context):
    return LLLnode.from_list(
        ['clamp', ['mload', MemoryPositions.MINNUM], args[0], ['mload', MemoryPositions.MAXNUM]], typ=BaseType("num"), pos=getpos(expr)
    )


# Can take either a literal number or a num/bytes32/address as an input
@signature(('num_literal', 'num', 'bytes32', 'address'))
def as_num256(expr, args, kwargs, context):
    if isinstance(args[0], int):
        if not(0 <= args[0] <= 2**256 - 1):
            raise InvalidLiteralException("Number out of range: " + str(expr.args[0].n), expr.args[0])
        return LLLnode.from_list(args[0], typ=BaseType('num256'), pos=getpos(expr))
    elif isinstance(args[0], LLLnode) and args[0].typ.typ in ('num', 'num_literal', 'address'):
        return LLLnode.from_list(['clampge', args[0], 0], typ=BaseType('num256'), pos=getpos(expr))
    elif isinstance(args[0], LLLnode):
        return LLLnode(value=args[0].value, args=args[0].args, typ=BaseType('num256'), pos=getpos(expr))
    else:
        raise InvalidLiteralException("Invalid input for num256: %r" % args[0], expr)


@signature(('num', 'num256', 'address'))
def as_bytes32(expr, args, kwargs, context):
    return LLLnode(value=args[0].value, args=args[0].args, typ=BaseType('bytes32'), pos=getpos(expr))


@signature('bytes', start='num', len='num')
def _slice(expr, args, kwargs, context):
    sub, start, length = args[0], kwargs['start'], kwargs['len']
    if not are_units_compatible(start.typ, BaseType("num")):
        raise TypeMismatchException("Type for slice start index must be a unitless number")
    # Expression representing the length of the slice
    if not are_units_compatible(length.typ, BaseType("num")):
        raise TypeMismatchException("Type for slice length must be a unitless number")
    # Node representing the position of the output in memory
    np = context.new_placeholder(ByteArrayType(maxlen=sub.typ.maxlen + 32))
    placeholder_node = LLLnode.from_list(np, typ=sub.typ, location='memory')
    placeholder_plus_32_node = LLLnode.from_list(np + 32, typ=sub.typ, location='memory')
    # Copies over bytearray data
    if sub.location == 'storage':
        adj_sub = LLLnode.from_list(
            ['add', ['sha3_32', sub], ['add', ['div', '_start', 32], 1]], typ=sub.typ, location=sub.location
        )
    else:
        adj_sub = LLLnode.from_list(
            ['add', sub, ['add', ['sub', '_start', ['mod', '_start', 32]], 32]], typ=sub.typ, location=sub.location
        )
    copier = make_byte_slice_copier(placeholder_plus_32_node, adj_sub, ['add', '_length', 32], sub.typ.maxlen)
    # New maximum length in the type of the result
    newmaxlen = length.value if not len(length.args) else sub.typ.maxlen
    out = ['with', '_start', start,
              ['with', '_length', length,
                  ['with', '_opos', ['add', placeholder_node, ['mod', '_start', 32]],
                       ['seq',
                           ['assert', ['lt', ['add', '_start', '_length'], sub.typ.maxlen]],
                           copier,
                           ['mstore', '_opos', '_length'],
                           '_opos']]]]
    return LLLnode.from_list(out, typ=ByteArrayType(newmaxlen), location='memory', pos=getpos(expr))


@signature('bytes')
def _len(expr, args, kwargs, context):
    return get_length(args[0])


def concat(expr, context):
    args = [Expr(arg, context).lll_node for arg in expr.args]
    if len(args) < 2:
        raise StructureException("Concat expects at least two arguments", expr)
    for expr_arg, arg in zip(expr.args, args):
        if not isinstance(arg.typ, ByteArrayType) and not is_base_type(arg.typ, 'bytes32') and not is_base_type(arg.typ, 'method_id'):
            raise TypeMismatchException("Concat expects byte arrays or bytes32 objects", expr_arg)
    # Maximum length of the output
    total_maxlen = sum([arg.typ.maxlen if isinstance(arg.typ, ByteArrayType) else 32 for arg in args])
    # Node representing the position of the output in memory
    placeholder = context.new_placeholder(ByteArrayType(total_maxlen))
    # Object representing the output
    seq = []
    # For each argument we are concatenating...
    for arg in args:
        # Start pasting into a position the starts at zero, and keeps
        # incrementing as we concatenate arguments
        placeholder_node = LLLnode.from_list(['add', placeholder, '_poz'], typ=ByteArrayType(total_maxlen), location='memory')
        placeholder_node_plus_32 = LLLnode.from_list(['add', ['add', placeholder, '_poz'], 32], typ=ByteArrayType(total_maxlen), location='memory')
        if isinstance(arg.typ, ByteArrayType):
            # Ignore empty strings
            if arg.typ.maxlen == 0:
                continue
            # Get the length of the current argument
            if arg.location == "memory":
                length = LLLnode.from_list(['mload', '_arg'], typ=BaseType('num'))
                argstart = LLLnode.from_list(['add', '_arg', 32], typ=arg.typ, location=arg.location)
            elif arg.location == "storage":
                length = LLLnode.from_list(['sload', ['sha3_32', '_arg']], typ=BaseType('num'))
                argstart = LLLnode.from_list(['add', ['sha3_32', '_arg'], 1], typ=arg.typ, location=arg.location)
            # Make a copier to copy over data from that argyument
            seq.append(['with', '_arg', arg,
                            ['seq',
                                make_byte_slice_copier(placeholder_node_plus_32,
                                                       argstart,
                                                       length,
                                                       arg.typ.maxlen),
                                # Change the position to start at the correct
                                # place to paste the next value
                                ['set', '_poz', ['add', '_poz', length]]]])
        elif isinstance(arg.typ, BaseType) and arg.typ.typ == "method_id":
            seq.append(['seq',
                            ['mstore', ['add', placeholder_node, 32], arg.value * 2**224],
                            ['set', '_poz', ['add', '_poz', 4]]])
        else:
            seq.append(['seq',
                            ['mstore', ['add', placeholder_node, 32], unwrap_location(arg)],
                            ['set', '_poz', ['add', '_poz', 32]]])
    # The position, after all arguments are processing, equals the total
    # length. Paste this in to make the output a proper bytearray
    seq.append(['mstore', placeholder, '_poz'])
    # Memory location of the output
    seq.append(placeholder)
    return LLLnode.from_list(
        ['with', '_poz', 0, ['seq'] + seq], typ=ByteArrayType(total_maxlen), location='memory', pos=getpos(expr), annotation='concat'
    )


@signature(('str_literal', 'bytes', 'bytes32'))
def _sha3(expr, args, kwargs, context):
    sub = args[0]
    # Can hash literals
    if isinstance(sub, bytes):
        return LLLnode.from_list(bytes_to_int(sha3(sub)), typ=BaseType('bytes32'), pos=getpos(expr))
    # Can hash bytes32 objects
    if is_base_type(sub.typ, 'bytes32'):
        return LLLnode.from_list(
            ['seq', ['mstore', MemoryPositions.FREE_VAR_SPACE, sub], ['sha3', MemoryPositions.FREE_VAR_SPACE, 32]], typ=BaseType('bytes32'),
            pos=getpos(expr)
        )
    # Copy the data to an in-memory array
    if sub.location == "memory":
        # If we are hashing a value in memory, no need to copy it, just hash in-place
        return LLLnode.from_list(
            ['with', '_sub', sub, ['sha3', ['add', '_sub', 32], ['mload', '_sub']]], typ=BaseType('bytes32'),
            pos=getpos(expr)
        )
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('num'))
    else:
        raise Exception("Unsupported location: %s" % sub.location)
    placeholder = context.new_placeholder(sub.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=sub.typ, location='memory')
    copier = make_byte_array_copier(placeholder_node, LLLnode.from_list('_sub', typ=sub.typ, location=sub.location))
    return LLLnode.from_list(
        ['with', '_sub', sub, ['seq', copier, ['sha3', ['add', placeholder, 32], lengetter]]], typ=BaseType('bytes32'),
        pos=getpos(expr)
    )


@signature('str_literal')
def method_id(expr, args, kwargs, context):
    method_id = fourbytes_to_int(sha3(args[0])[:4])
    return LLLnode(method_id, typ=BaseType('method_id'), pos=getpos(expr))


@signature('bytes32', 'num256', 'num256', 'num256')
def ecrecover(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(
        context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
    )
    return LLLnode.from_list(['seq',
                              ['mstore', placeholder_node, args[0]],
                              ['mstore', ['add', placeholder_node, 32], args[1]],
                              ['mstore', ['add', placeholder_node, 64], args[2]],
                              ['mstore', ['add', placeholder_node, 96], args[3]],
                              ['pop', ['call', 3000, 1, 0, placeholder_node, 128, MemoryPositions.FREE_VAR_SPACE, 32]],
                              ['mload', MemoryPositions.FREE_VAR_SPACE]], typ=BaseType('address'), pos=getpos(expr))


def avo(arg, ind):
    return unwrap_location(add_variable_offset(arg, LLLnode.from_list(ind, 'num')))


@signature('num256[2]', 'num256[2]')
def ecadd(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(
        context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
    )

    o = LLLnode.from_list(['seq',
                              ['mstore', placeholder_node, avo(args[0], 0)],
                              ['mstore', ['add', placeholder_node, 32], avo(args[0], 1)],
                              ['mstore', ['add', placeholder_node, 64], avo(args[1], 0)],
                              ['mstore', ['add', placeholder_node, 96], avo(args[1], 1)],
                              ['assert', ['call', 500, 6, 0, placeholder_node, 128, placeholder_node, 64]],
                              placeholder_node], typ=ListType(BaseType('num256'), 2), pos=getpos(expr), location='memory')
    return o


@signature('num256[2]', 'num256')
def ecmul(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(
        context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
    )

    o = LLLnode.from_list(['seq',
                              ['mstore', placeholder_node, avo(args[0], 0)],
                              ['mstore', ['add', placeholder_node, 32], avo(args[0], 1)],
                              ['mstore', ['add', placeholder_node, 64], args[1]],
                              ['assert', ['call', 40000, 7, 0, placeholder_node, 96, placeholder_node, 64]],
                              placeholder_node], typ=ListType(BaseType('num256'), 2), pos=getpos(expr), location='memory')
    return o


@signature('bytes', 'num', type=Optional('name_literal', 'bytes32'))
def extract32(expr, args, kwargs, context):
    sub, index = args
    ret_type = kwargs['type']
    # Get length and specific element
    if sub.location == "memory":
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('num'))
        elementgetter = lambda index: LLLnode.from_list(
            ['mload', ['add', '_sub', ['add', 32, ['mul', 32, index]]]], typ=BaseType('num')
        )
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('num'))
        elementgetter = lambda index: LLLnode.from_list(
            ['sload', ['add', ['sha3_32', '_sub'], ['add', 1, index]]], typ=BaseType('num')
        )
    # Special case: index known to be a multiple of 32
    if isinstance(index.value, int) and not index.value % 32:
        o = LLLnode.from_list(
            ['with', '_sub', sub, elementgetter(['div', ['clamp', 0, index, ['sub', lengetter, 32]], 32])],
            typ=BaseType(ret_type), annotation='extracting 32 bytes'
        )
    # General case
    else:
        o = LLLnode.from_list(
            ['with', '_sub', sub,
             ['with', '_len', lengetter,
              ['with', '_index', ['clamp', 0, index, ['sub', '_len', 32]],
               ['with', '_mi32', ['mod', '_index', 32],
                ['with', '_di32', ['div', '_index', 32],
                 ['if',
                  '_mi32',
                  ['add',
                   ['mul',
                    elementgetter('_di32'),
                    ['exp', 256, '_mi32']],
                   ['div',
                    elementgetter(['add', '_di32', 1]),
                    ['exp', 256, ['sub', 32, '_mi32']]]],
                  elementgetter('_di32')]]]]]],
        typ=BaseType(ret_type), pos=getpos(expr), annotation='extracting 32 bytes')
    if ret_type == 'num128':
        return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINNUM], o, ['mload', MemoryPositions.MAXNUM]], typ=BaseType("num"), pos=getpos(expr))
    elif ret_type == 'address':
        return LLLnode.from_list(['uclamplt', o, ['mload', MemoryPositions.ADDRSIZE]], typ=BaseType(ret_type), pos=getpos(expr))
    else:
        return o


@signature('bytes')
def bytes_to_num(expr, args, kwargs, context):
    return byte_array_to_num(args[0], expr, 'num')


@signature(('num_literal', 'num', 'decimal'), 'str_literal')
def as_wei_value(expr, args, kwargs, context):
    # Denominations
    if args[1] == b"wei":
        denomination = 1
    elif args[1] in (b"kwei", b"ada", b"lovelace"):
        denomination = 10**3
    elif args[1] == b"babbage":
        denomination = 10**6
    elif args[1] in (b"shannon", b"gwei"):
        denomination = 10**9
    elif args[1] == b"szabo":
        denomination = 10**12
    elif args[1] == b"finney":
        denomination = 10**15
    elif args[1] == b"ether":
        denomination = 10**18
    else:
        raise InvalidLiteralException("Invalid denomination: %s" % args[1], expr.args[1])
    # Compute the amount of wei and return that value
    if isinstance(args[0], (int, float)):
        numstring, num, den = get_number_as_fraction(expr.args[0], context)
        if denomination % den:
            raise InvalidLiteralException("Too many decimal places: %s" % numstring, expr.args[0])
        sub = num * denomination // den
    elif args[0].typ.typ == 'num':
        sub = ['mul', args[0], denomination]
    else:
        sub = ['div', ['mul', args[0], denomination], DECIMAL_DIVISOR]
    return LLLnode.from_list(sub, typ=BaseType('num', {'wei': 1}), location=None, pos=getpos(expr))


zero_value = LLLnode.from_list(0, typ=BaseType('num', {'wei': 1}))


@signature('address', 'bytes', outsize='num_literal', gas='num', value=Optional('num', zero_value))
def raw_call(expr, args, kwargs, context):
    to, data = args
    gas, value, outsize = kwargs['gas'], kwargs['value'], kwargs['outsize']
    if context.is_constant:
        raise ConstancyViolationException("Cannot make calls from a constant function", expr)
    if value != zero_value:
        enforce_units(value.typ, get_keyword(expr, 'value'),
                      BaseType('num', {'wei': 1}))
    placeholder = context.new_placeholder(data.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=data.typ, location='memory')
    copier = make_byte_array_copier(placeholder_node, data)
    output_placeholder = context.new_placeholder(ByteArrayType(outsize))
    output_node = LLLnode.from_list(output_placeholder, typ=ByteArrayType(outsize), location='memory')
    z = LLLnode.from_list(['seq',
                              copier,
                              ['assert', ['call', gas, to, value, ['add', placeholder_node, 32], ['mload', placeholder_node],
                                         ['add', output_node, 32], outsize]],
                              ['mstore', output_node, outsize],
                              output_node], typ=ByteArrayType(outsize), location='memory', pos=getpos(expr))
    return z


@signature('address', 'num')
def send(expr, args, kwargs, context):
    to, value = args
    if context.is_constant:
        raise ConstancyViolationException("Cannot send ether inside a constant function!", expr)
    enforce_units(value.typ, expr.args[1], BaseType('num', {'wei': 1}))
    return LLLnode.from_list(['assert', ['call', 0, to, value, 0, 0, 0, 0]], typ=None, pos=getpos(expr))


@signature('address')
def selfdestruct(expr, args, kwargs, context):
    if context.is_constant:
        raise ConstancyViolationException("Cannot %s inside a constant function!" % expr.func.id, expr.func)
    return LLLnode.from_list(['selfdestruct', args[0]], typ=None, pos=getpos(expr))


@signature('num')
def blockhash(expr, args, kwargs, contact):
    return LLLnode.from_list(['blockhash', ['uclamplt', ['clampge', args[0], ['sub', ['number'], 256]], 'number']],
                             typ=BaseType('bytes32'), pos=getpos(expr))


@signature('bytes', '*')
def _RLPlist(expr, args, kwargs, context):
    # Second argument must be a list of types
    if not isinstance(args[1], ast.List):
        raise TypeMismatchException("Expecting list of types for second argument", args[1])
    if len(args[1].elts) == 0:
        raise TypeMismatchException("RLP list must have at least one item", expr)
    if len(args[1].elts) > 32:
        raise TypeMismatchException("RLP list must have at most 32 items", expr)
    # Get the output format
    _format = []
    for arg in args[1].elts:
        if isinstance(arg, ast.Name) and arg.id == "bytes":
            subtyp = ByteArrayType(args[0].typ.maxlen)
        else:
            subtyp = parse_type(arg, 'memory')
            if not isinstance(subtyp, BaseType):
                raise TypeMismatchException("RLP lists only accept BaseTypes and byte arrays", arg)
            if not is_base_type(subtyp, ('num', 'num256', 'bytes32', 'address', 'bool')):
                raise TypeMismatchException("Unsupported base type: %s" % subtyp.typ, arg)
        _format.append(subtyp)
    output_type = TupleType(_format)
    output_placeholder_type = ByteArrayType((2 * len(_format) + 1 + get_size_of_type(output_type)) * 32)
    output_placeholder = context.new_placeholder(output_placeholder_type)
    output_node = LLLnode.from_list(output_placeholder, typ=output_placeholder_type, location='memory')
    # Create a decoder for each element in the tuple
    decoder = []
    for i, typ in enumerate(_format):
        # Decoder for bytes32
        if is_base_type(typ, 'bytes32'):
            decoder.append(LLLnode.from_list(
                ['seq',
                    ['assert', ['eq', ['mload', ['add', output_node, ['mload', ['add', output_node, 32 * i]]]], 32]],
                    ['mload', ['add', 32, ['add', output_node, ['mload', ['add', output_node, 32 * i]]]]]],
            typ, annotation='getting and checking bytes32 item'))
        # Decoder for address
        elif is_base_type(typ, 'address'):
            decoder.append(LLLnode.from_list(
                ['seq',
                    ['assert', ['eq', ['mload', ['add', output_node, ['mload', ['add', output_node, 32 * i]]]], 20]],
                    ['mod',
                         ['mload', ['add', 20, ['add', output_node, ['mload', ['add', output_node, 32 * i]]]]],
                         ['mload', MemoryPositions.ADDRSIZE]]],
            typ, annotation='getting and checking address item'))
        # Decoder for bytes
        elif isinstance(typ, ByteArrayType):
            decoder.append(LLLnode.from_list(
                ['add', output_node, ['mload', ['add', output_node, 32 * i]]],
            typ, location='memory', annotation='getting byte array'))
        # Decoder for num and num256
        elif is_base_type(typ, ('num', 'num256')):
            bytez = LLLnode.from_list(
                ['add', output_node, ['mload', ['add', output_node, 32 * i]]],
            typ, location='memory', annotation='getting and checking %s' % typ.typ)
            decoder.append(byte_array_to_num(bytez, expr, typ.typ))
        # Decoder for bools
        elif is_base_type(typ, ('bool')):
            # This is basically a really clever way to test for a length-prefixed one or zero. We take the 32 bytes
            # starting one byte *after* the start of the length declaration; this includes the last 31 bytes of the
            # length and the first byte of the value. 0 corresponds to length 0, first byte 0, and 257 corresponds
            # to length 1, first byte \x01
            decoder.append(LLLnode.from_list(
                ['with', '_ans', ['mload', ['add', 1, ['add', output_node, ['mload', ['add', output_node, 32 * i]]]]],
                    ['seq', ['assert', ['or', ['eq', '_ans', 0], ['eq', '_ans', 257]]], ['div', '_ans', 257]]],
            typ, annotation='getting and checking bool'))
        else:
            raise Exception("Type not yet supported")
    # Copy the input data to memory
    if args[0].location == "memory":
        variable_pointer = args[0]
    elif args[0].location == "storage":
        placeholder = context.new_placeholder(args[0].typ)
        placeholder_node = LLLnode.from_list(placeholder, typ=args[0].typ, location='memory')
        copier = make_byte_array_copier(placeholder_node, LLLnode.from_list('_ptr', typ=args[0].typ, location=args[0].location))
        variable_pointer = ['with', '_ptr', args[0], ['seq', copier, placeholder_node]]
    else:
        raise Exception("Location not yet supported")
    # Decode the input data
    initial_setter = LLLnode.from_list(
        ['seq',
            ['with', '_sub', variable_pointer,
                ['pop', ['call',
                         1500 + 400 * len(_format) + 10 * len(args),
                         LLLnode.from_list(RLP_DECODER_ADDRESS, annotation='RLP decoder'),
                         0,
                         ['add', '_sub', 32],
                         ['mload', '_sub'],
                         output_node,
                         64 * len(_format) + 32 + 32 * get_size_of_type(output_type)]]],
            ['assert', ['eq', ['mload', output_node], 32 * len(_format) + 32]]],
        typ=None)
    # Shove the input data decoder in front of the first variable decoder
    decoder[0] = LLLnode.from_list(['seq', initial_setter, decoder[0]], typ=decoder[0].typ, location=decoder[0].location)
    return LLLnode.from_list(["multi"] + decoder, typ=output_type, location='memory', pos=getpos(expr))


@signature('*', 'bytes')
def raw_log(expr, args, kwargs, context):
    if not isinstance(args[0], ast.List) or len(args[0].elts) > 4:
        raise StructureException("Expecting a list of 0-4 topics as first argument", args[0])
    topics = []
    for elt in args[0].elts:
        arg = Expr.parse_value_expr(elt, context)
        if not is_base_type(arg.typ, 'bytes32'):
            raise TypeMismatchException("Expecting a bytes32 argument as topic", elt)
        topics.append(arg)
    if args[1].location == "memory":
        return LLLnode.from_list(["with", "_arr", args[1], ["log" + str(len(topics)), ["add", "_arr", 32], ["mload", "_arr"]] + topics],
                                 typ=None, pos=getpos(expr))
    placeholder = context.new_placeholder(args[1].typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=args[1].typ, location='memory')
    copier = make_byte_array_copier(placeholder_node, LLLnode.from_list('_sub', typ=args[1].typ, location=args[1].location))
    return LLLnode.from_list(
        ["with", "_sub", args[1],
            ["seq",
                copier,
                ["log" + str(len(topics)), ["add", placeholder_node, 32], ["mload", placeholder_node]] + topics]],
    typ=None, pos=getpos(expr))


@signature('num256', 'num256')
def bitwise_and(expr, args, kwargs, context):
    return LLLnode.from_list(['and', args[0], args[1]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def bitwise_or(expr, args, kwargs, context):
    return LLLnode.from_list(['or', args[0], args[1]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def bitwise_xor(expr, args, kwargs, context):
    return LLLnode.from_list(['xor', args[0], args[1]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_add(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                # Checks that: a + b >= a
                                ['assert', ['ge', ['add', args[0], args[1]], args[0]]],
                                ['add', args[0], args[1]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_sub(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                # Checks that: a >= b
                                ['assert', ['ge', args[0], args[1]]],
                                ['sub', args[0], args[1]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_mul(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                # Checks that: a == 0 || a / b == b
                                ['assert', ['or', ['iszero', args[0]],
                                ['eq', ['div', ['mul', args[0], args[1]], args[0]], args[1]]]],
                                ['mul', args[0], args[1]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_div(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                # Checks that:  b != 0
                                ['assert', args[1]],
                                ['div', args[0], args[1]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_exp(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                ['assert', ['or', ['or', ['eq', args[1], 1], ['iszero', args[1]]],
                                ['lt', args[0], ['exp', args[0], args[1]]]]],
                                ['exp', args[0], args[1]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_mod(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                ['assert', args[1]],
                                ['mod', args[0], args[1]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256', 'num256')
def num256_addmod(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                ['assert', args[2]],
                                ['assert', ['or', ['iszero', args[1]], ['gt', ['add', args[0], args[1]], args[0]]]],
                                ['addmod', args[0], args[1], args[2]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256', 'num256')
def num256_mulmod(expr, args, kwargs, context):
    return LLLnode.from_list(['seq',
                                ['assert', args[2]],
                                ['assert', ['or', ['iszero', args[0]],
                                ['eq', ['div', ['mul', args[0], args[1]], args[0]], args[1]]]],
                                ['mulmod', args[0], args[1], args[2]]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256')
def bitwise_not(expr, args, kwargs, context):
    return LLLnode.from_list(['not', args[0]], typ=BaseType('num256'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_gt(expr, args, kwargs, context):
    return LLLnode.from_list(['gt', args[0], args[1]], typ=BaseType('bool'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_ge(expr, args, kwargs, context):
    return LLLnode.from_list(['ge', args[0], args[1]], typ=BaseType('bool'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_lt(expr, args, kwargs, context):
    return LLLnode.from_list(['lt', args[0], args[1]], typ=BaseType('bool'), pos=getpos(expr))


@signature('num256', 'num256')
def num256_le(expr, args, kwargs, context):
    return LLLnode.from_list(['le', args[0], args[1]], typ=BaseType('bool'), pos=getpos(expr))


@signature('num256', 'num')
def shift(expr, args, kwargs, context):
    return LLLnode.from_list(['with', '_v', args[0],
                                ['with', '_s', args[1],
                                    # If second argument is positive, left-shift so multiply by a power of two
                                    # If it is negative, divide by a power of two
                                    # node that if the abs of the second argument >= 256, then in the EVM
                                    # 2**(second arg) = 0, and multiplying OR dividing by 0 gives 0
                                    ['if', ['sle', '_s', 0],
                                           ['div', '_v', ['exp', 2, ['sub', 0, '_s']]],
                                           ['mul', '_v', ['exp', 2, '_s']]]]],
    typ=BaseType('num256'), pos=getpos(expr))


@signature('address', value=Optional('num', zero_value))
def create_with_code_of(expr, args, kwargs, context):
    value = kwargs['value']
    if value != zero_value:
        enforce_units(value.typ, get_keyword(expr, 'value'),
                      BaseType('num', {'wei': 1}))
    if context.is_constant:
        raise ConstancyViolationException("Cannot make calls from a constant function", expr)
    placeholder = context.new_placeholder(ByteArrayType(96))
    kode = b'`.`\x0c`\x009`.`\x00\xf36`\x00`\x007a\x10\x00`\x006`\x00s\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xf4\x15XWa\x10\x00`\x00\xf3'
    assert len(kode) <= 64
    high = bytes_to_int(kode[:32])
    low = bytes_to_int((kode + b'\x00' * 32)[47:79])
    return LLLnode.from_list(['seq',
                                ['mstore', placeholder, high],
                                ['mstore', ['add', placeholder, 27], ['mul', args[0], 2**96]],
                                ['mstore', ['add', placeholder, 47], low],
                                ['clamp_nonzero', ['create', value, placeholder, 64]]], typ=BaseType('address'), pos=getpos(expr), add_gas_estimate=10000)


@signature(('num', 'decimal', 'num256'), ('num', 'decimal', 'num256'))
def _min(expr, args, kwargs, context):
    return minmax(expr, args, kwargs, context, True)


@signature(('num', 'decimal', 'num256'), ('num', 'decimal', 'num256'))
def _max(expr, args, kwargs, context):
    return minmax(expr, args, kwargs, context, False)


def minmax(expr, args, kwargs, context, is_min):
    left, right = args[0], args[1]
    if not are_units_compatible(left.typ, right.typ) and not are_units_compatible(right.typ, left.typ):
        raise TypeMismatchException("Units must be compatible", expr)
    if left.typ.typ == 'num256':
        comparator = 'gt' if is_min else 'lt'
    else:
        comparator = 'sgt' if is_min else 'slt'
    if left.typ.typ == right.typ.typ:
        o = ['if', [comparator, '_l', '_r'], '_r', '_l']
        otyp = left.typ
    elif left.typ.typ == 'num' and right.typ.typ == 'decimal':
        o = ['if', [comparator, ['mul', '_l', DECIMAL_DIVISOR], '_r'], '_r', ['mul', '_l', DECIMAL_DIVISOR]]
        otyp = 'decimal'
    elif left.typ.typ == 'decimal' and right.typ.typ == 'num':
        o = ['if', [comparator, '_l', ['mul', '_r', DECIMAL_DIVISOR]], ['mul', '_r', DECIMAL_DIVISOR], '_l']
        otyp = 'decimal'
    else:
        raise TypeMismatchException("Minmax types incompatible: %s %s" % (left.typ.typ, right.typ.typ))
    return LLLnode.from_list(['with', '_l', left, ['with', '_r', right, o]], typ=otyp, pos=getpos(expr))


dispatch_table = {
    'floor': floor,
    'decimal': decimal,
    'as_unitless_number': as_unitless_number,
    'as_num128': as_num128,
    'as_num256': as_num256,
    'as_bytes32': as_bytes32,
    'slice': _slice,
    'len': _len,
    'concat': concat,
    'sha3': _sha3,
    'method_id': method_id,
    'keccak256': _sha3,
    'ecrecover': ecrecover,
    'ecadd': ecadd,
    'ecmul': ecmul,
    'extract32': extract32,
    'bytes_to_num': bytes_to_num,
    'as_wei_value': as_wei_value,
    'raw_call': raw_call,
    'RLPList': _RLPlist,
    'blockhash': blockhash,
    'bitwise_and': bitwise_and,
    'bitwise_or': bitwise_or,
    'bitwise_xor': bitwise_xor,
    'bitwise_not': bitwise_not,
    'num256_add': num256_add,
    'num256_sub': num256_sub,
    'num256_mul': num256_mul,
    'num256_div': num256_div,
    'num256_exp': num256_exp,
    'num256_mod': num256_mod,
    'num256_addmod': num256_addmod,
    'num256_mulmod': num256_mulmod,
    'num256_gt': num256_gt,
    'num256_ge': num256_ge,
    'num256_lt': num256_lt,
    'num256_le': num256_le,
    'shift': shift,
    'create_with_code_of': create_with_code_of,
    'min': _min,
    'max': _max,
}

stmt_dispatch_table = {
    'send': send,
    'selfdestruct': selfdestruct,
    'raw_call': raw_call,
    'raw_log': raw_log,
    'create_with_code_of': create_with_code_of,
}
