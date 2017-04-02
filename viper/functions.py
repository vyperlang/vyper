from .exceptions import InvalidTypeException, TypeMismatchException, \
    VariableDeclarationException, StructureException, ConstancyViolationException, \
    InvalidTypeException, InvalidLiteralException
from .types import NodeType, BaseType, ListType, MappingType, StructType, \
    MixedType, NullType, ByteArrayType, TupleType
from .types import base_types, parse_type, canonicalize_type, is_base_type, \
    is_numeric_type, get_size_of_type, is_varname_valid
from .types import combine_units, are_units_compatible, set_default_units
from .parser_utils import LLLnode, make_byte_array_copier, get_number_as_fraction, \
    get_length_if_0x_prefixed, byte_array_to_num
from .utils import fourbytes_to_int, hex_to_int, bytes_to_int, \
    DECIMAL_DIVISOR, RESERVED_MEMORY, ADDRSIZE_POS, MAXNUM_POS, MINNUM_POS, \
    MAXDECIMAL_POS, MINDECIMAL_POS, FREE_VAR_SPACE, BLANK_SPACE, FREE_LOOP_INDEX, \
    RLP_DECODER_ADDRESS
import ast

class Optional():
    def __init__(self, typ, default):
        self.typ = typ
        self.default = default

def process_arg(index, arg, expected_arg_typelist, function_name, context):
    from .parser import parse_expr, parse_value_expr
    if isinstance(expected_arg_typelist, Optional):
        expected_arg_typelist = expected_arg_typelist.typ
    if not isinstance(expected_arg_typelist, tuple):
        expected_arg_typelist = (expected_arg_typelist, )
    vsub = None
    for expected_arg in expected_arg_typelist:
        if expected_arg == 'num_literal' and isinstance(arg, ast.Num) and get_length_if_0x_prefixed(arg, context) is None:
            return arg.n
        elif expected_arg == 'name_literal' and isinstance(arg, ast.Name):
            return arg.id
        elif expected_arg == '*':
            return arg
        elif expected_arg == 'bytes':
            sub = parse_expr(arg, context)
            if isinstance(sub.typ, ByteArrayType):
                return sub
        else:
            vsub = vsub or parse_value_expr(arg, context)
            if is_base_type(vsub.typ, expected_arg):
                return vsub
    if len(expected_arg_typelist) == 1:
        raise TypeMismatchException("Expecting %s for argument %r of %s" %
                                    (expected_arg, index, function_name), arg)
    else:
        raise TypeMismatchException("Expecting one of %r for argument %r of %s" %
                                    (expected_arg_typelist, index, function_name), arg)
        return arg.id

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
                    raise StructureException("Not enough arguments for function %s", element)
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
            return f(element, subs, kwsubs, context)
        return g
    return decorator

@signature('decimal')
def floor(expr, args, kwargs, context):
    return LLLnode.from_list(['sdiv', args[0], DECIMAL_DIVISOR], typ=BaseType('num', args[0].typ.unit, args[0].typ.positional))

@signature(('num', 'decimal'))
def decimal(expr, args, kwargs, context):
    if args[0].typ.typ == 'decimal':
        return args[0]
    else:
        return LLLnode.from_list(['mul', args[0], DECIMAL_DIVISOR], typ=BaseType('decimal', args[0].typ.unit, args[0].typ.positional))

@signature(('num', 'decimal'))
def as_unitless_number(expr, args, kwargs, context):
    return LLLnode(value=args[0].value, args=args[0].args, typ=BaseType(args[0].typ.typ, {}))

@signature(('num', 'bytes32', 'num256', 'address'))
def as_num128(expr, args, kwargs, context):
    return LLLnode.from_list(['clamp', ['mload', MINNUM_POS], args[0], ['mload', MAXNUM_POS]], typ=BaseType("num"))

# Can take either a literal number or a num/bytes32/address as an input
@signature(('num_literal', 'num', 'bytes32', 'address'))
def as_num256(expr, args, kwargs, context):
    if isinstance(args[0], int):
        if not(0 <= args[0] <= 2**256 - 1):
            raise InvalidLiteralException("Number out of range: "+str(expr.args[0].n), expr.args[0])
        return LLLnode.from_list(args[0], typ=BaseType('num256', None))
    else:
        return LLLnode(value=args[0].value, args=args[0].args, typ=BaseType('num256'))

@signature(('num', 'num256', 'address'))
def as_bytes32(expr, args, kwargs, context):
    return LLLnode(value=args[0].value, args=args[0].args, typ=BaseType('bytes32'))

@signature('bytes', start='num', len='num')
def _slice(expr, args, kwargs, context):
    sub, start, length = args[0], kwargs['start'], kwargs['len']
    if not are_units_compatible(start.typ, BaseType("num")):
        raise TypeMismatchException("Type for slice start index must be a unitless number")
    # Expression representing the length of the slice
    if not are_units_compatible(length.typ, BaseType("num")):
        raise TypeMismatchException("Type for slice length must be a unitless number")
    # Node representing the position of the output in memory
    placeholder_node = LLLnode.from_list(context.new_placeholder(sub.typ), typ=sub.typ, location='memory')
    # Copies over bytearray data
    copier = make_byte_array_copier(placeholder_node, sub, '_start', '_length')
    # New maximum length in the type of the result
    newmaxlen = length.value if not len(length.args) else sub.typ.maxlen
    out = ['with', '_start', start,
              ['with', '_length', length,
                  ['seq',
                       ['assert', ['lt', ['add', '_start', '_length'], sub.typ.maxlen]],
                       copier,
                       ['mstore', ['add', placeholder_node, '_start'], '_length'],
                       ['add', placeholder_node, '_start']
           ]]]
    return LLLnode.from_list(out, typ=ByteArrayType(newmaxlen), location='memory')

@signature('bytes')
def _len(expr, args, kwargs, context):
    if args[0].location == "calldata":
        return LLLnode.from_list(['calldataload', ['add', 4, args[0]]], typ=BaseType('num'))
    elif args[0].location == "memory":
        return LLLnode.from_list(['mload', args[0]], typ=BaseType('num'))
    elif args[0].location == "storage":
        return LLLnode.from_list(['sload', ['sha3_32', args[0]]], typ=BaseType('num'))

def concat(expr, context):
    from .parser import parse_expr, unwrap_location
    args = [parse_expr(arg, context) for arg in expr.args]
    if len(args) < 2:
        raise StructureException("Concat expects at least two arguments", expr)
    for expr_arg, arg in zip(expr.args, args):
        if not isinstance(arg.typ, ByteArrayType) and not is_base_type(arg.typ, 'bytes32'):
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
        if isinstance(arg.typ, ByteArrayType):
            # Get the length of the current argument
            if arg.location == "calldata":
                length = LLLnode.from_list(['calldataload', ['add', 4, '_arg']], typ=BaseType('num'))
            elif arg.location == "memory":
                length = LLLnode.from_list(['mload', '_arg'], typ=BaseType('num'))
            elif arg.location == "storage":
                length = LLLnode.from_list(['sload', ['sha3_32', '_arg']], typ=BaseType('num'))
            # Make a copier to copy over data from that argyument
            seq.append(['with', '_arg', arg,
                            ['seq',
                                make_byte_array_copier(placeholder_node,
                                                       LLLnode.from_list('_arg', typ=arg.typ, location=arg.location), 0),
                                # Change the position to start at the correct
                                # place to paste the next value
                                ['set', '_poz', ['add', '_poz', length]]]])
        else:
            seq.append(['seq',
                            ['mstore', ['add', placeholder_node, 32], unwrap_location(arg)],
                            ['set', '_poz', ['add', '_poz', 32]]])
    # The position, after all arguments are processing, equals the total
    # length. Paste this in to make the output a proper bytearray
    seq.append(['mstore', placeholder, '_poz'])
    # Memory location of the output
    seq.append(placeholder)
    return LLLnode.from_list(['with', '_poz', 0, ['seq'] + seq], typ=ByteArrayType(total_maxlen), location='memory')

@signature(('bytes', 'bytes32'))
def _sha3(expr, args, kwargs, context):
    sub = args[0]
    # Can hash bytes32 objects
    if is_base_type(sub.typ, 'bytes32'):
        return LLLnode.from_list(['seq', ['mstore', FREE_VAR_SPACE, sub], ['sha3', FREE_VAR_SPACE, 32]], typ=BaseType('bytes32'))
    # Copy the data to an in-memory array
    if sub.location == "calldata":
        lengetter = LLLnode.from_list(['calldataload', ['add', 4, '_sub']], typ=BaseType('num'))
    elif sub.location == "memory":
        # If we are hashing a value in memory, no need to copy it, just hash in-place
        return LLLnode.from_list(['with', '_sub', sub, ['sha3', ['add', '_sub', 32], ['mload', '_sub']]], typ=BaseType('bytes32'))
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('num'))
    else:
        raise Exception("Unsupported location: %s" % sub.location)
    placeholder = context.new_placeholder(sub.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=sub.typ, location='memory')
    copier = make_byte_array_copier(placeholder_node, LLLnode.from_list('_sub', typ=sub.typ, location=sub.location))
    return LLLnode.from_list(['with', '_sub', sub,
                                ['seq',
                                    copier,
                                    ['sha3', ['add', placeholder, 32], lengetter]]], typ=BaseType('bytes32'))

@signature('bytes32', 'num256', 'num256', 'num256')
def ecrecover(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory')
    return LLLnode.from_list(['seq',
                              ['mstore', placeholder_node, args[0]],
                              ['mstore', ['add', placeholder_node, 32], args[1]],
                              ['mstore', ['add', placeholder_node, 64], args[2]],
                              ['mstore', ['add', placeholder_node, 96], args[3]],
                              ['pop', ['call', 3000, 1, 0, placeholder_node, 128, FREE_VAR_SPACE, 32]],
                              ['mload', FREE_VAR_SPACE]], typ=BaseType('address'))

@signature('bytes', 'num', type=Optional('name_literal', 'bytes32'))
def extract32(expr, args, kwargs, context):
    sub, index = args
    ret_type = kwargs['type']
    # Get length and specific element
    if sub.location == "calldata":
        lengetter = LLLnode.from_list(['calldataload', ['add', 4, '_sub']], typ=BaseType('num'))
        elementgetter = lambda index: LLLnode.from_list(['calldataload', ['add', ['add', 36, '_sub'], ['mul', 32, index]]], typ=BaseType('num'))
    elif sub.location == "memory":
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('num'))
        elementgetter = lambda index: LLLnode.from_list(['mload', ['add', '_sub', ['add', 32, ['mul', 32, index]]]], typ=BaseType('num'))
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('num'))
        elementgetter = lambda index: LLLnode.from_list(['sload', ['add', ['sha3_32', '_sub'], ['add', 1, index]]], typ=BaseType('num'))
    # Special case: index known to be a multiple of 32
    if isinstance(index.value, int) and not index.value % 32:
        o = LLLnode.from_list(['with', '_sub', sub, elementgetter(['div', ['clamp', 0, index, ['sub', lengetter, 32]], 32])], typ=BaseType(ret_type))
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
        typ=BaseType(ret_type))
    if ret_type == 'num128':
        return LLLnode.from_list(['clamp', ['mload', MINNUM_POS], o, ['mload', MAXNUM_POS]], typ=BaseType("num"))
    elif ret_type == 'address':
        return LLLnode.from_list(['uclamplt', o, ['mload', ADDRSIZE_POS]], typ=BaseType(ret_type))
    else:
        return o

@signature('bytes')
def bytes_to_num(expr, args, kwargs, context):
    return byte_array_to_num(args[0], expr, 'num')

@signature(('num_literal', 'num', 'decimal'), 'name_literal')
def as_wei_value(expr, args, kwargs, context):
    # Denominations
    if args[1] == "wei":
        denomination = 1
    elif args[1] in ("kwei", "ada", "lovelace"):
        denomination = 10**3
    elif args[1] == "babbage":
        denomination = 10**6
    elif args[1] in ("shannon", "gwei"):
        denomination = 10**9
    elif args[1] == "szabo":
        denomination = 10**12
    elif args[1] == "finney":
        denomination = 10**15
    elif args[1] == "ether":
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
    return LLLnode.from_list(sub, typ=BaseType('num', {'wei': 1}), location=None)

zero_value = LLLnode.from_list(0, typ=BaseType('num', {'wei': 1}))

@signature('address', 'bytes', outsize='num_literal', gas='num', value=Optional('num', zero_value))
def raw_call(expr, args, kwargs, context):
    to, data = args
    gas, value, outsize = kwargs['gas'], kwargs['value'], kwargs['outsize']
    if context.is_constant:
        raise ConstancyViolationException("Cannot make calls from a constant function", expr)
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
                              output_node], typ=ByteArrayType(outsize), location='memory')
    return z

@signature('address', 'num')
def send(expr, args, kwargs, context):
    to, value = args
    if context.is_constant:
        raise ConstancyViolationException("Cannot send ether inside a constant function!", expr)
    if not are_units_compatible(value.typ, BaseType('num', {'wei': 1})):
        raise TypeMismatchException("Expecting a wei_value as argument to send. Try as_wei_value or declaring the variable as a wei_value.",
                                    expr.args[1])
    return LLLnode.from_list(['pop', ['call', 0, to, value, 0, 0, 0, 0]], typ=None)

@signature('address')
def selfdestruct(expr, args, kwargs, context):
    if context.is_constant:
        raise ConstancyViolationException("Cannot %s inside a constant function!" % expr.func.id, expr.func)
    return LLLnode.from_list(['selfdestruct', args[0]], typ=None)

@signature('num')
def blockhash(expr, args, kwargs, contact):
    return LLLnode.from_list(['blockhash', ['uclamp', ['sub', ['number'], 256], args[0], ['sub', ['number'], 1]]], typ=BaseType('bytes32'))

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
    output_placeholder_type = ByteArrayType(2 * len(_format) + 1 + get_size_of_type(output_type))
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
            typ))
        # Decoder for address
        elif is_base_type(typ, 'address'):
            decoder.append(LLLnode.from_list(
                ['seq',
                    ['assert', ['eq', ['mload', ['add', output_node, ['mload', ['add', output_node, 32 * i]]]], 20]],
                    ['mod',
                         ['mload', ['add', 20, ['add', output_node, ['mload', ['add', output_node, 32 * i]]]]],
                         ['mload', ADDRSIZE_POS]]],
            typ))
        # Decoder for bytes
        elif isinstance(typ, ByteArrayType):
            decoder.append(LLLnode.from_list(
                ['add', output_node, ['mload', ['add', output_node, 32 * i]]],
            typ, location='memory'))
        # Decoder for num and num256
        elif is_base_type(typ, ('num', 'num256')):
            bytez = LLLnode.from_list(
                ['add', output_node, ['mload', ['add', output_node, 32 * i]]],
            typ, location='memory')
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
            typ))
        else:
            raise Exception("Type not yet supported")
    # Copy the input data to memory
    if args[0].location == "memory":
        variable_pointer = args[0]
    else:
        if args[0].location == "calldata":
            lengetter = LLLnode.from_list(['calldataload', ['add', 4, '_ptr']], typ=BaseType('num'))
        elif args[0].location == "storage":
            lengetter = LLLnode.from_list(['sload', ['sha3_32', '_ptr']], typ=BaseType('num'))
        else:
            raise Exception("Location not yet supported")
        placeholder = context.new_placeholder(args[0].typ)
        placeholder_node = LLLnode.from_list(placeholder, typ=args[0].typ, location='memory')
        copier = make_byte_array_copier(placeholder_node, LLLnode.from_list('_ptr', typ=args[0].typ, location=args[0].location))
        variable_pointer = ['with', '_ptr', args[0], ['seq', copier, placeholder_node]]
    # Decode the input data
    initial_setter = LLLnode.from_list(
        ['seq',
            ['with', '_sub', variable_pointer,
                ['pop', ['call',
                         10000 + 500 * len(_format) + 10 * len(args),
                         RLP_DECODER_ADDRESS,
                         0,
                         ['add', '_sub', 32],
                         ['mload', '_sub'],
                         output_node,
                         64 * len(_format) + 32 + 32 * get_size_of_type(output_type)]]],
            ['sstore', 4, ['mload', output_node]],
            ['assert', ['eq', ['mload', output_node], 32 * len(_format) + 32]]],
        typ=None)
    # Shove the input data decoder in front of the first variable decoder
    decoder[0] = LLLnode.from_list(['seq', initial_setter, decoder[0]], typ=decoder[0].typ, location=decoder[0].location)
    return LLLnode.from_list(["multi"] + decoder, typ=output_type, location='memory')


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
    'ecrecover': ecrecover,
    'extract32': extract32,
    'bytes_to_num': bytes_to_num,
    'as_wei_value': as_wei_value,
    'raw_call': raw_call,
    'RLPList': _RLPlist,
    'blockhash': blockhash
}

stmt_dispatch_table = {
    'send': send,
    'suicide': selfdestruct,
    'selfdestruct': selfdestruct,
}
