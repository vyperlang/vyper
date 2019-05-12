import hashlib

from vyper import ast
from vyper.exceptions import (
    ConstancyViolationException,
    InvalidLiteralException,
    ParserException,
    StructureException,
    TypeMismatchException,
)
from vyper.parser.expr import (
    Expr,
)
from vyper.parser.parser_utils import (
    LLLnode,
    add_variable_offset,
    byte_array_to_num,
    get_length,
    get_number_as_fraction,
    getpos,
    make_byte_array_copier,
    make_byte_slice_copier,
    unwrap_location,
)
from vyper.signatures.function_signature import (
    VariableRecord,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ListType,
    StringType,
    TupleType,
    are_units_compatible,
    get_size_of_type,
    is_base_type,
)
from vyper.types.convert import (
    convert,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    RLP_DECODER_ADDRESS,
    MemoryPositions,
    SizeLimits,
    bytes_to_int,
    fourbytes_to_int,
    sha3,
)

from .signatures import (
    Optional,
    signature,
)

SHA256_ADDRESS = 2
SHA256_BASE_GAS = 60
SHA256_PER_WORD_GAS = 12


def enforce_units(typ, obj, expected):
    if not are_units_compatible(typ, expected):
        raise TypeMismatchException("Invalid units", obj)


def get_keyword(expr, keyword):
    for kw in expr.keywords:
        if kw.arg == keyword:
            return kw.value
    # This should never happen, as kwargs['value'] will KeyError first.
    # Leaving exception for other use cases.
    raise Exception("Keyword %s not found" % keyword)  # pragma: no cover


@signature('decimal')
def floor(expr, args, kwargs, context):
    return LLLnode.from_list(
        [
            'if',
            ['slt', args[0], 0],
            ['sdiv', ['sub', args[0], DECIMAL_DIVISOR - 1], DECIMAL_DIVISOR],
            ['sdiv', args[0], DECIMAL_DIVISOR]
        ],
        typ=BaseType('int128', args[0].typ.unit, args[0].typ.positional),
        pos=getpos(expr)
    )


@signature('decimal')
def ceil(expr, args, kwards, context):
    return LLLnode.from_list(
        [
            'if',
            ['slt', args[0], 0],
            ['sdiv', args[0], DECIMAL_DIVISOR],
            ['sdiv', ['add', args[0], DECIMAL_DIVISOR - 1], DECIMAL_DIVISOR]
        ],
        typ=BaseType('int128', args[0].typ.unit, args[0].typ.positional),
        pos=getpos(expr)
    )


@signature(('uint256', 'int128', 'decimal'))
def as_unitless_number(expr, args, kwargs, context):
    return LLLnode(
        value=args[0].value,
        args=args[0].args,
        typ=BaseType(args[0].typ.typ, {}),
        pos=getpos(expr),
    )


def _convert(expr, context):
    return convert(expr, context)


@signature(('bytes32', 'bytes', 'string'), start='int128', len='int128')
def _slice(expr, args, kwargs, context):

    sub, start, length = args[0], kwargs['start'], kwargs['len']
    if not are_units_compatible(start.typ, BaseType('int128')):
        raise TypeMismatchException("Type for slice start index must be a unitless number", expr)
    # Expression representing the length of the slice
    if not are_units_compatible(length.typ, BaseType('int128')):
        raise TypeMismatchException("Type for slice length must be a unitless number", expr)

    if is_base_type(sub.typ, 'bytes32'):
        if (start.typ.is_literal and length.typ.is_literal) and \
           not (0 <= start.value + length.value <= 32):
            raise InvalidLiteralException(
                'Invalid start / length values needs to be between 0 and 32.',
                expr,
            )
        sub_typ_maxlen = 32
    else:
        sub_typ_maxlen = sub.typ.maxlen

    # Get returntype string or bytes
    if isinstance(args[0].typ, ByteArrayType) or is_base_type(sub.typ, 'bytes32'):
        ReturnType = ByteArrayType
    else:
        ReturnType = StringType

    # Node representing the position of the output in memory
    np = context.new_placeholder(ReturnType(maxlen=sub_typ_maxlen + 32))
    placeholder_node = LLLnode.from_list(np, typ=sub.typ, location='memory')
    placeholder_plus_32_node = LLLnode.from_list(np + 32, typ=sub.typ, location='memory')
    # Copies over bytearray data
    if sub.location == 'storage':
        adj_sub = LLLnode.from_list(
            ['add', ['sha3_32', sub], ['add', ['div', '_start', 32], 1]],
            typ=sub.typ,
            location=sub.location,
        )
    else:
        adj_sub = LLLnode.from_list(
            ['add', sub, ['add', ['sub', '_start', ['mod', '_start', 32]], 32]],
            typ=sub.typ,
            location=sub.location,
        )

    if is_base_type(sub.typ, 'bytes32'):
        adj_sub = LLLnode.from_list(
            sub.args[0], typ=sub.typ, location="memory"
        )

    copier = make_byte_slice_copier(
        placeholder_plus_32_node,
        adj_sub,
        ['add', '_length', 32],
        sub_typ_maxlen,
        pos=getpos(expr),
    )
    # New maximum length in the type of the result
    newmaxlen = length.value if not len(length.args) else sub_typ_maxlen
    if is_base_type(sub.typ, 'bytes32'):
        maxlen = 32
    else:
        maxlen = ['mload', Expr(sub, context=context).lll_node]  # Retrieve length of the bytes.

    out = [
        'with', '_start', start, [
            'with', '_length', length, [
                'with', '_opos', ['add', placeholder_node, ['mod', '_start', 32]], [
                    'seq',
                    ['assert', ['le', ['add', '_start', '_length'], maxlen]],
                    copier,
                    ['mstore', '_opos', '_length'],
                    '_opos'
                ],
            ],
        ],
    ]
    return LLLnode.from_list(out, typ=ReturnType(newmaxlen), location='memory', pos=getpos(expr))


@signature(('bytes', 'string'))
def _len(expr, args, kwargs, context):
    return get_length(args[0])


def concat(expr, context):
    args = [Expr(arg, context).lll_node for arg in expr.args]
    if len(args) < 2:
        raise StructureException("Concat expects at least two arguments", expr)

    prev_type = ''
    for _, (expr_arg, arg) in enumerate(zip(expr.args, args)):
        if not isinstance(arg.typ, ByteArrayLike) and not is_base_type(arg.typ, 'bytes32'):
            raise TypeMismatchException("Concat expects string, bytes or bytes32 objects", expr_arg)

        current_type = (
            'bytes'
            if isinstance(arg.typ, ByteArrayType) or is_base_type(arg.typ, 'bytes32')
            else 'string'
        )
        if prev_type and current_type != prev_type:
            raise TypeMismatchException(
                (
                    "Concat expects consistant use of string or byte types, "
                    "user either bytes or string."
                ),
                expr_arg,
            )
        prev_type = current_type

    if current_type == 'string':
        ReturnType = StringType
    else:
        ReturnType = ByteArrayType

    # Maximum length of the output
    total_maxlen = sum([
        arg.typ.maxlen if isinstance(arg.typ, ByteArrayType) else 32 for arg in args
    ])
    # Node representing the position of the output in memory
    placeholder = context.new_placeholder(ReturnType(total_maxlen))
    # Object representing the output
    seq = []
    # For each argument we are concatenating...
    for arg in args:
        # Start pasting into a position the starts at zero, and keeps
        # incrementing as we concatenate arguments
        placeholder_node = LLLnode.from_list(
            ['add', placeholder, '_poz'],
            typ=ReturnType(total_maxlen),
            location='memory',
        )
        placeholder_node_plus_32 = LLLnode.from_list(
            ['add', ['add', placeholder, '_poz'], 32],
            typ=ReturnType(total_maxlen),
            location='memory',
        )
        if isinstance(arg.typ, ReturnType):
            # Ignore empty strings
            if arg.typ.maxlen == 0:
                continue
            # Get the length of the current argument
            if arg.location == "memory":
                length = LLLnode.from_list(['mload', '_arg'], typ=BaseType('int128'))
                argstart = LLLnode.from_list(
                    ['add', '_arg', 32],
                    typ=arg.typ,
                    location=arg.location,
                )
            elif arg.location == "storage":
                length = LLLnode.from_list(['sload', ['sha3_32', '_arg']], typ=BaseType('int128'))
                argstart = LLLnode.from_list(
                    ['add', ['sha3_32', '_arg'], 1],
                    typ=arg.typ,
                    location=arg.location,
                )
            # Make a copier to copy over data from that argument
            seq.append([
                'with', '_arg', arg, [
                    'seq',
                    make_byte_slice_copier(
                        placeholder_node_plus_32,
                        argstart,
                        length,
                        arg.typ.maxlen, pos=getpos(expr),
                    ),
                    # Change the position to start at the correct
                    # place to paste the next value
                    ['set', '_poz', ['add', '_poz', length]],
                ],
            ])
        else:
            seq.append([
                'seq',
                ['mstore', ['add', placeholder_node, 32], unwrap_location(arg)],
                ['set', '_poz', ['add', '_poz', 32]],
            ])
    # The position, after all arguments are processing, equals the total
    # length. Paste this in to make the output a proper bytearray
    seq.append(['mstore', placeholder, '_poz'])
    # Memory location of the output
    seq.append(placeholder)
    return LLLnode.from_list(
        ['with', '_poz', 0, ['seq'] + seq],
        typ=ReturnType(total_maxlen),
        location='memory',
        pos=getpos(expr),
        annotation='concat',
    )


@signature(('bytes_literal', 'str_literal', 'bytes', 'string', 'bytes32'))
def _sha3(expr, args, kwargs, context):
    sub = args[0]
    # Can hash literals
    if isinstance(sub, bytes):
        return LLLnode.from_list(
            bytes_to_int(sha3(sub)),
            typ=BaseType('bytes32'),
            pos=getpos(expr)
        )
    # Can hash bytes32 objects
    if is_base_type(sub.typ, 'bytes32'):
        return LLLnode.from_list(
            [
                'seq',
                ['mstore', MemoryPositions.FREE_VAR_SPACE, sub],
                ['sha3', MemoryPositions.FREE_VAR_SPACE, 32]
            ],
            typ=BaseType('bytes32'),
            pos=getpos(expr),
        )
    # Copy the data to an in-memory array
    if sub.location == "memory":
        # If we are hashing a value in memory, no need to copy it, just hash in-place
        return LLLnode.from_list(
            ['with', '_sub', sub, ['sha3', ['add', '_sub', 32], ['mload', '_sub']]],
            typ=BaseType('bytes32'),
            pos=getpos(expr),
        )
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('int128'))
    else:
        # This should never happen, but just left here for future compiler-writers.
        raise Exception("Unsupported location: %s" % sub.location)  # pragma: no test
    placeholder = context.new_placeholder(sub.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=sub.typ, location='memory')
    copier = make_byte_array_copier(
        placeholder_node,
        LLLnode.from_list('_sub', typ=sub.typ, location=sub.location),
    )
    return LLLnode.from_list(
        [
            'with', '_sub', sub, [
                'seq',
                copier,
                ['sha3', ['add', placeholder, 32], lengetter]
            ],
        ],
        typ=BaseType('bytes32'),
        pos=getpos(expr)
    )


def _make_sha256_call(inp_start, inp_len, out_start, out_len):
    return [
        'assert', [
            'call',
            ['gas'],  # gas
            SHA256_ADDRESS,  # address
            0,  # value
            inp_start,
            inp_len,
            out_start,
            out_len
        ]
    ]


@signature(('bytes_literal', 'str_literal', 'bytes', 'string', 'bytes32'))
def sha256(expr, args, kwargs, context):
    sub = args[0]
    # Literal input
    if isinstance(sub, bytes):
        return LLLnode.from_list(
            bytes_to_int(hashlib.sha256(sub).digest()),
            typ=BaseType('bytes32'),
            pos=getpos(expr)
        )
    # bytes32 input
    elif is_base_type(sub.typ, 'bytes32'):
        return LLLnode.from_list(
            [
                'seq',
                ['mstore', MemoryPositions.FREE_VAR_SPACE, sub],
                _make_sha256_call(
                    inp_start=MemoryPositions.FREE_VAR_SPACE,
                    inp_len=32,
                    out_start=MemoryPositions.FREE_VAR_SPACE,
                    out_len=32
                ),
                ['mload', MemoryPositions.FREE_VAR_SPACE]  # push value onto stack
            ],
            typ=BaseType('bytes32'),
            pos=getpos(expr),
            add_gas_estimate=SHA256_BASE_GAS + 1 * SHA256_PER_WORD_GAS
        )
    # bytearay-like input
    if sub.location == "storage":
        # Copy storage to memory
        placeholder = context.new_placeholder(sub.typ)
        placeholder_node = LLLnode.from_list(placeholder, typ=sub.typ, location='memory')
        copier = make_byte_array_copier(
            placeholder_node,
            LLLnode.from_list('_sub', typ=sub.typ, location=sub.location),
        )
        return LLLnode.from_list(
            [
                'with', '_sub', sub, [
                    'seq',
                    copier,
                    _make_sha256_call(
                        inp_start=['add', placeholder, 32],
                        inp_len=['mload', placeholder],
                        out_start=MemoryPositions.FREE_VAR_SPACE,
                        out_len=32
                    ),
                    ['mload', MemoryPositions.FREE_VAR_SPACE]
                ],
            ],
            typ=BaseType('bytes32'),
            pos=getpos(expr),
            add_gas_estimate=SHA256_BASE_GAS + sub.typ.maxlen * SHA256_PER_WORD_GAS
        )
    elif sub.location == "memory":
        return LLLnode.from_list(
            [
                'with', '_sub', sub, [
                    'seq',
                    _make_sha256_call(
                        inp_start=['add', '_sub', 32],
                        inp_len=['mload', '_sub'],
                        out_start=MemoryPositions.FREE_VAR_SPACE,
                        out_len=32
                    ),
                    ['mload', MemoryPositions.FREE_VAR_SPACE]
                ]
            ],
            typ=BaseType('bytes32'),
            pos=getpos(expr),
            add_gas_estimate=SHA256_BASE_GAS + sub.typ.maxlen * SHA256_PER_WORD_GAS
        )
    else:
        # This should never happen, but just left here for future compiler-writers.
        raise Exception("Unsupported location: %s" % sub.location)  # pragma: no test


@signature('str_literal', 'name_literal')
def method_id(expr, args, kwargs, context):
    if b' ' in args[0]:
        raise TypeMismatchException('Invalid function signature no spaces allowed.')
    method_id = fourbytes_to_int(sha3(args[0])[:4])
    if args[1] == 'bytes32':
        return LLLnode(method_id, typ=BaseType('bytes32'), pos=getpos(expr))
    elif args[1] == 'bytes[4]':
        placeholder = LLLnode.from_list(context.new_placeholder(ByteArrayType(4)))
        return LLLnode.from_list(
            ['seq',
                ['mstore', ['add', placeholder, 4], method_id],
                ['mstore', placeholder, 4], placeholder],
            typ=ByteArrayType(4), location='memory', pos=getpos(expr))
    else:
        raise StructureException('Can only produce bytes32 or bytes[4] as outputs')


@signature('bytes32', 'uint256', 'uint256', 'uint256')
def ecrecover(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(
        context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
    )
    return LLLnode.from_list([
        'seq',
        ['mstore', placeholder_node, args[0]],
        ['mstore', ['add', placeholder_node, 32], args[1]],
        ['mstore', ['add', placeholder_node, 64], args[2]],
        ['mstore', ['add', placeholder_node, 96], args[3]],
        ['pop', ['call', 3000, 1, 0, placeholder_node, 128, MemoryPositions.FREE_VAR_SPACE, 32]],
        ['mload', MemoryPositions.FREE_VAR_SPACE],
    ], typ=BaseType('address'), pos=getpos(expr))


def avo(arg, ind, pos):
    return unwrap_location(add_variable_offset(arg, LLLnode.from_list(ind, 'int128'), pos=pos))


@signature('uint256[2]', 'uint256[2]')
def ecadd(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(
        context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
    )
    pos = getpos(expr)
    o = LLLnode.from_list([
        'seq',
        ['mstore', placeholder_node, avo(args[0], 0, pos)],
        ['mstore', ['add', placeholder_node, 32], avo(args[0], 1, pos)],
        ['mstore', ['add', placeholder_node, 64], avo(args[1], 0, pos)],
        ['mstore', ['add', placeholder_node, 96], avo(args[1], 1, pos)],
        ['assert', ['call', 500, 6, 0, placeholder_node, 128, placeholder_node, 64]],
        placeholder_node,
    ], typ=ListType(BaseType('uint256'), 2), pos=getpos(expr), location='memory')
    return o


@signature('uint256[2]', 'uint256')
def ecmul(expr, args, kwargs, context):
    placeholder_node = LLLnode.from_list(
        context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
    )
    pos = getpos(expr)
    o = LLLnode.from_list([
        'seq',
        ['mstore', placeholder_node, avo(args[0], 0, pos)],
        ['mstore', ['add', placeholder_node, 32], avo(args[0], 1, pos)],
        ['mstore', ['add', placeholder_node, 64], args[1]],
        ['assert', ['call', 40000, 7, 0, placeholder_node, 96, placeholder_node, 64]],
        placeholder_node,
    ], typ=ListType(BaseType('uint256'), 2), pos=pos, location='memory')
    return o


def _memory_element_getter(index):
    return LLLnode.from_list(
        ['mload', ['add', '_sub', ['add', 32, ['mul', 32, index]]]],
        typ=BaseType('int128'),
    )


def _storage_element_getter(index):
    return LLLnode.from_list(
        ['sload', ['add', ['sha3_32', '_sub'], ['add', 1, index]]],
        typ=BaseType('int128'),
    )


@signature('bytes', 'int128', type=Optional('name_literal', 'bytes32'))
def extract32(expr, args, kwargs, context):
    sub, index = args
    ret_type = kwargs['type']
    # Get length and specific element
    if sub.location == "memory":
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('int128'))
        elementgetter = _memory_element_getter
    elif sub.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('int128'))
        elementgetter = _storage_element_getter
    # TODO: unclosed if/elif clause.  Undefined behavior if `sub.location`
    # isn't one of `memory`/`storage`

    # Special case: index known to be a multiple of 32
    if isinstance(index.value, int) and not index.value % 32:
        o = LLLnode.from_list(
            [
                'with', '_sub', sub,
                elementgetter(['div', ['clamp', 0, index, ['sub', lengetter, 32]], 32])
            ],
            typ=BaseType(ret_type),
            annotation='extracting 32 bytes',
        )
    # General case
    else:
        o = LLLnode.from_list([
            'with', '_sub', sub, [
                'with', '_len', lengetter, [
                    'with', '_index', ['clamp', 0, index, ['sub', '_len', 32]], [
                        'with', '_mi32', ['mod', '_index', 32], [
                            'with', '_di32', ['div', '_index', 32],
                            [
                                'if',
                                '_mi32',
                                [
                                    'add',
                                    ['mul', elementgetter('_di32'), ['exp', 256, '_mi32']],
                                    [
                                        'div',
                                        elementgetter(['add', '_di32', 1]),
                                        ['exp', 256, ['sub', 32, '_mi32']],
                                    ],
                                ],
                                elementgetter('_di32'),
                            ],
                        ],
                    ],
                ],
            ],
        ], typ=BaseType(ret_type), pos=getpos(expr), annotation='extracting 32 bytes')
    if ret_type == 'int128':
        return LLLnode.from_list(
            ['clamp', ['mload', MemoryPositions.MINNUM], o, ['mload', MemoryPositions.MAXNUM]],
            typ=BaseType('int128'),
            pos=getpos(expr),
        )
    elif ret_type == 'address':
        return LLLnode.from_list(
            ['uclamplt', o, ['mload', MemoryPositions.ADDRSIZE]],
            typ=BaseType(ret_type),
            pos=getpos(expr),
        )
    else:
        return o


@signature(('num_literal', 'int128', 'uint256', 'decimal'), 'str_literal')
def as_wei_value(expr, args, kwargs, context):
    # Denominations
    names_denom = {
        (b"wei", ): 1,
        (b"femtoether", b"kwei", b"babbage"): 10**3,
        (b"picoether", b"mwei", b"lovelace"): 10**6,
        (b"nanoether", b"gwei", b"shannon"): 10**9,
        (b"microether", b"szabo", ): 10**12,
        (b"milliether", b"finney", ): 10**15,
        (b"ether", ): 10**18,
        (b"kether", b"grand"): 10**21,
    }

    for names, denom in names_denom.items():
        if args[1] in names:
            denomination = denom
            break
    else:
        raise InvalidLiteralException(
            "Invalid denomination: %s, valid denominations are: %s" % (
                args[1],
                ",".join(x[0].decode() for x in names_denom)
            ),
            expr.args[1]
        )
    # Compute the amount of wei and return that value
    if isinstance(args[0], (int, float)):
        expr_args_0 = expr.args[0]
        # On constant reference fetch value node of constant assignment.
        if context.constants.ast_is_constant(expr.args[0]):
            expr_args_0 = context.constants._constants_ast[expr.args[0].id]
        numstring, num, den = get_number_as_fraction(expr_args_0, context)
        if denomination % den:
            raise InvalidLiteralException("Too many decimal places: %s" % numstring, expr.args[0])
        sub = num * denomination // den
    elif args[0].typ.is_literal:
        if args[0].value <= 0:
            raise InvalidLiteralException("Negative wei value not allowed", expr)
        sub = ['mul', args[0].value, denomination]
    elif args[0].typ.typ == 'uint256':
        sub = ['mul', args[0], denomination]
    else:
        sub = ['div', ['mul', args[0], denomination], DECIMAL_DIVISOR]

    return LLLnode.from_list(
        sub,
        typ=BaseType('uint256', {'wei': 1}),
        location=None,
        pos=getpos(expr),
    )


zero_value = LLLnode.from_list(0, typ=BaseType('uint256', {'wei': 1}))
false_value = LLLnode.from_list(0, typ=BaseType('bool', is_literal=True))


@signature(
    'address',
    'bytes',
    outsize='num_literal',
    gas='uint256',
    value=Optional('uint256', zero_value),
    delegate_call=Optional('bool', false_value),
)
def raw_call(expr, args, kwargs, context):
    to, data = args
    gas, value, outsize, delegate_call = (
        kwargs['gas'],
        kwargs['value'],
        kwargs['outsize'],
        kwargs['delegate_call'],
    )
    if delegate_call.typ.is_literal is False:
        raise TypeMismatchException(
            'The delegate_call parameter has to be a static/literal boolean value.'
        )
    if context.is_constant():
        raise ConstancyViolationException(
            "Cannot make calls from %s" % context.pp_constancy(),
            expr,
        )
    if value != zero_value:
        enforce_units(
            value.typ,
            get_keyword(expr, 'value'),
            BaseType('uint256', {'wei': 1}),
        )
    placeholder = context.new_placeholder(data.typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=data.typ, location='memory')
    copier = make_byte_array_copier(placeholder_node, data, pos=getpos(expr))
    output_placeholder = context.new_placeholder(ByteArrayType(outsize))
    output_node = LLLnode.from_list(
        output_placeholder,
        typ=ByteArrayType(outsize),
        location='memory',
    )

    if delegate_call.value == 1:
        z = LLLnode.from_list(
            [
                'seq',
                copier,
                [
                    'assert',
                    [
                        'delegatecall',
                        gas,
                        to,
                        ['add', placeholder_node, 32],
                        ['mload', placeholder_node],
                        ['add', output_node, 32],
                        outsize,
                    ],
                ],
                ['mstore', output_node, outsize],
                output_node,
            ],
            typ=ByteArrayType(outsize),
            location='memory',
            pos=getpos(expr),
        )
    else:
        z = LLLnode.from_list(
            [
                'seq',
                copier,
                [
                    'assert',
                    [
                        'call',
                        gas,
                        to,
                        value,
                        ['add', placeholder_node, 32],
                        ['mload', placeholder_node],
                        ['add', output_node, 32],
                        outsize,
                    ],
                ],
                ['mstore', output_node, outsize],
                output_node,
            ],
            typ=ByteArrayType(outsize), location='memory', pos=getpos(expr)
        )
    return z


@signature('address', 'uint256')
def send(expr, args, kwargs, context):
    to, value = args
    if context.is_constant():
        raise ConstancyViolationException(
            "Cannot send ether inside %s!" % context.pp_constancy(),
            expr,
        )
    enforce_units(value.typ, expr.args[1], BaseType('uint256', {'wei': 1}))
    return LLLnode.from_list(
        ['assert', ['call', 0, to, value, 0, 0, 0, 0]],
        typ=None,
        pos=getpos(expr),
    )


@signature('address')
def selfdestruct(expr, args, kwargs, context):
    if context.is_constant():
        raise ConstancyViolationException(
            "Cannot %s inside %s!" % (expr.func.id, context.pp_constancy()),
            expr.func,
        )
    return LLLnode.from_list(['selfdestruct', args[0]], typ=None, pos=getpos(expr))


@signature(('uint256'))
def blockhash(expr, args, kwargs, contact):
    return LLLnode.from_list(
        ['blockhash', ['uclamplt', ['clampge', args[0], ['sub', ['number'], 256]], 'number']],
        typ=BaseType('bytes32'),
        pos=getpos(expr),
    )


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
            subtyp = context.parse_type(arg, 'memory')
            if not isinstance(subtyp, BaseType):
                raise TypeMismatchException("RLP lists only accept BaseTypes and byte arrays", arg)
            if not is_base_type(subtyp, ('int128', 'uint256', 'bytes32', 'address', 'bool')):
                raise TypeMismatchException("Unsupported base type: %s" % subtyp.typ, arg)
        _format.append(subtyp)
    output_type = TupleType(_format)
    output_placeholder_type = ByteArrayType(
        (2 * len(_format) + 1 + get_size_of_type(output_type)) * 32,
    )
    output_placeholder = context.new_placeholder(output_placeholder_type)
    output_node = LLLnode.from_list(
        output_placeholder,
        typ=output_placeholder_type,
        location='memory',
    )
    # Create a decoder for each element in the tuple
    decoder = []
    for i, typ in enumerate(_format):
        # Decoder for bytes32
        if is_base_type(typ, 'bytes32'):
            decoder.append(LLLnode.from_list(
                [
                    'seq',
                    [
                        'assert',
                        [
                            'eq',
                            [
                                'mload',
                                [
                                    'add',
                                    output_node,
                                    ['mload', ['add', output_node, 32 * i]],
                                ],
                            ],
                            32,
                        ],
                    ],
                    [
                        'mload',
                        [
                            'add',
                            32,
                            [
                                'add',
                                output_node,
                                ['mload', ['add', output_node, 32 * i]],
                            ],
                        ],
                    ],
                ],
                typ,
                annotation='getting and checking bytes32 item',
            ))
        # Decoder for address
        elif is_base_type(typ, 'address'):
            decoder.append(LLLnode.from_list(
                [
                    'seq',
                    [
                        'assert',
                        [
                            'eq',
                            [
                                'mload',
                                [
                                    'add',
                                    output_node,
                                    ['mload', ['add', output_node, 32 * i]],
                                ],
                            ],
                            20,
                        ]
                    ],
                    [
                        'mod',
                        [
                            'mload',
                            [
                                'add',
                                20,
                                ['add', output_node, ['mload', ['add', output_node, 32 * i]]],
                            ],
                        ],
                        ['mload', MemoryPositions.ADDRSIZE],
                    ]
                ],
                typ,
                annotation='getting and checking address item',
            ))
        # Decoder for bytes
        elif isinstance(typ, ByteArrayType):
            decoder.append(LLLnode.from_list(
                [
                    'add',
                    output_node,
                    ['mload', ['add', output_node, 32 * i]],
                ],
                typ,
                location='memory',
                annotation='getting byte array',
            ))
        # Decoder for num and uint256
        elif is_base_type(typ, ('int128', 'uint256')):
            bytez = LLLnode.from_list(
                [
                    'add',
                    output_node,
                    ['mload', ['add', output_node, 32 * i]],
                ],
                typ,
                location='memory',
                annotation='getting and checking %s' % typ.typ,
            )
            decoder.append(byte_array_to_num(bytez, expr, typ.typ))
        # Decoder for bools
        elif is_base_type(typ, ('bool')):
            # This is basically a really clever way to test for a
            # length-prefixed one or zero. We take the 32 bytes starting one
            # byte *after* the start of the length declaration; this includes
            # the last 31 bytes of the length and the first byte of the value.
            # 0 corresponds to length 0, first byte 0, and 257 corresponds to
            # length 1, first byte \x01
            decoder.append(LLLnode.from_list(
                [
                    'with', '_ans', [
                        'mload',
                        [
                            'add',
                            1,
                            ['add', output_node, ['mload', ['add', output_node, 32 * i]]]
                        ],
                    ],
                    [
                        'seq',
                        ['assert', ['or', ['eq', '_ans', 0], ['eq', '_ans', 257]]],
                        ['div', '_ans', 257],
                    ],
                ],
                typ,
                annotation='getting and checking bool',
            ))
        else:
            # Should never reach because of top level base level check.
            raise Exception("Type not yet supported")  # pragma: no cover
    # Copy the input data to memory
    if args[0].location == "memory":
        variable_pointer = args[0]
    elif args[0].location == "storage":
        placeholder = context.new_placeholder(args[0].typ)
        placeholder_node = LLLnode.from_list(placeholder, typ=args[0].typ, location='memory')
        copier = make_byte_array_copier(
            placeholder_node,
            LLLnode.from_list('_ptr', typ=args[0].typ, location=args[0].location),
        )
        variable_pointer = ['with', '_ptr', args[0], ['seq', copier, placeholder_node]]
    else:
        # Should never reach because of top level base level check.
        raise Exception("Location not yet supported")  # pragma: no cover
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
    decoder[0] = LLLnode.from_list(
        ['seq', initial_setter, decoder[0]],
        typ=decoder[0].typ,
        location=decoder[0].location,
    )
    return LLLnode.from_list(
        ["multi"] + decoder,
        typ=output_type,
        location='memory',
        pos=getpos(expr),
    )


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
        return LLLnode.from_list([
            "with", "_arr", args[1], [
                "log" + str(len(topics)),
                ["add", "_arr", 32],
                ["mload", "_arr"],
            ] + topics
        ], typ=None, pos=getpos(expr))
    placeholder = context.new_placeholder(args[1].typ)
    placeholder_node = LLLnode.from_list(placeholder, typ=args[1].typ, location='memory')
    copier = make_byte_array_copier(
        placeholder_node,
        LLLnode.from_list('_sub', typ=args[1].typ, location=args[1].location),
        pos=getpos(expr),
    )
    return LLLnode.from_list(
        [
            "with", "_sub", args[1],
            [
                "seq",
                copier,
                [
                    "log" + str(len(topics)),
                    ["add", placeholder_node, 32],
                    ["mload", placeholder_node],
                ] + topics
            ],
        ],
        typ=None,
        pos=getpos(expr),
    )


@signature('uint256', 'uint256')
def bitwise_and(expr, args, kwargs, context):
    return LLLnode.from_list(['and', args[0], args[1]], typ=BaseType('uint256'), pos=getpos(expr))


@signature('uint256', 'uint256')
def bitwise_or(expr, args, kwargs, context):
    return LLLnode.from_list(['or', args[0], args[1]], typ=BaseType('uint256'), pos=getpos(expr))


@signature('uint256', 'uint256')
def bitwise_xor(expr, args, kwargs, context):
    return LLLnode.from_list(['xor', args[0], args[1]], typ=BaseType('uint256'), pos=getpos(expr))


@signature('uint256', 'uint256', 'uint256')
def uint256_addmod(expr, args, kwargs, context):
    return LLLnode.from_list(
        [
            'seq',
            ['assert', args[2]],
            ['assert', ['or', ['iszero', args[1]], ['gt', ['add', args[0], args[1]], args[0]]]],
            ['addmod', args[0], args[1], args[2]],
        ],
        typ=BaseType('uint256'),
        pos=getpos(expr),
    )


@signature('uint256', 'uint256', 'uint256')
def uint256_mulmod(expr, args, kwargs, context):
    return LLLnode.from_list(
        [
            'seq',
            ['assert', args[2]],
            ['assert', [
                'or',
                ['iszero', args[0]],
                ['eq', ['div', ['mul', args[0], args[1]], args[0]], args[1]],
            ]],
            ['mulmod', args[0], args[1], args[2]],
        ],
        typ=BaseType('uint256'),
        pos=getpos(expr),
    )


@signature('uint256')
def bitwise_not(expr, args, kwargs, context):
    return LLLnode.from_list(['not', args[0]], typ=BaseType('uint256'), pos=getpos(expr))


@signature('uint256', 'int128')
def shift(expr, args, kwargs, context):
    return LLLnode.from_list(
        [
            'with', '_v', args[0], [
                'with', '_s', args[1], [
                    # If second argument is positive, left-shift so multiply by a power of two
                    # If it is negative, divide by a power of two
                    # node that if the abs of the second argument >= 256, then in the EVM
                    # 2**(second arg) = 0, and multiplying OR dividing by 0 gives 0
                    'if',
                    ['slt', '_s', 0],
                    ['div', '_v', ['exp', 2, ['sub', 0, '_s']]],
                    ['mul', '_v', ['exp', 2, '_s']]
                ],
            ],
        ],
        typ=BaseType('uint256'),
        pos=getpos(expr),
    )


def get_create_forwarder_to_bytecode():
    from vyper.compile_lll import (
        assembly_to_evm,
        num_to_bytearray
    )
    code_a = [
        'PUSH1', 0x33,
        'PUSH1', 0x0c,
        'PUSH1', 0x00,
        'CODECOPY',
        'PUSH1', 0x33,
        'PUSH1', 0x00,
        'RETURN',
        'CALLDATASIZE',
        'PUSH1', 0x00,
        'PUSH1', 0x00,
        'CALLDATACOPY',
        'PUSH2', num_to_bytearray(0x1000),
        'PUSH1', 0x00,
        'CALLDATASIZE',
        'PUSH1', 0x00,
        'PUSH20',  # [address to delegate to]
    ]
    code_b = [
        'GAS',
        'DELEGATECALL',
        'PUSH1', 0x2c,  # jumpdest of whole program.
        'JUMPI',
        'PUSH1', 0x0,
        'DUP1',
        'REVERT',
        'JUMPDEST',
        'PUSH2', num_to_bytearray(0x1000),
        'PUSH1', 0x00,
        'RETURN'
    ]
    return assembly_to_evm(code_a)[0] + (b'\x00' * 20) + assembly_to_evm(code_b)[0]


@signature('address', value=Optional('uint256', zero_value))
def create_forwarder_to(expr, args, kwargs, context):

    value = kwargs['value']
    if value != zero_value:
        enforce_units(value.typ, get_keyword(expr, 'value'),
                      BaseType('uint256', {'wei': 1}))
    if context.is_constant():
        raise ConstancyViolationException(
            "Cannot make calls from %s" % context.pp_constancy(),
            expr,
        )
    placeholder = context.new_placeholder(ByteArrayType(96))

    kode = get_create_forwarder_to_bytecode()
    high = bytes_to_int(kode[:32])
    low = bytes_to_int((kode + b'\x00' * 32)[47:79])

    return LLLnode.from_list(
        [
            'seq',
            ['mstore', placeholder, high],
            ['mstore', ['add', placeholder, 27], ['mul', args[0], 2**96]],
            ['mstore', ['add', placeholder, 47], low],
            ['clamp_nonzero', ['create', value, placeholder, 96]],
        ],
        typ=BaseType('address'),
        pos=getpos(expr),
        add_gas_estimate=11000,
    )


@signature(('int128', 'decimal', 'uint256'), ('int128', 'decimal', 'uint256'))
def _min(expr, args, kwargs, context):
    return minmax(expr, args, kwargs, context, True)


@signature(('int128', 'decimal', 'uint256'), ('int128', 'decimal', 'uint256'))
def _max(expr, args, kwargs, context):
    return minmax(expr, args, kwargs, context, False)


def minmax(expr, args, kwargs, context, is_min):
    def _can_compare_with_uint256(operand):
        if operand.typ.typ == 'uint256':
            return True
        elif operand.typ.typ == 'int128' and operand.typ.is_literal and SizeLimits.in_bounds('uint256', operand.value):  # noqa: E501
            return True
        return False

    left, right = args[0], args[1]
    if not are_units_compatible(left.typ, right.typ) and not are_units_compatible(right.typ, left.typ):  # noqa: E501
        raise TypeMismatchException("Units must be compatible", expr)
    if left.typ.typ == 'uint256':
        comparator = 'gt' if is_min else 'lt'
    else:
        comparator = 'sgt' if is_min else 'slt'
    if left.typ.typ == right.typ.typ:
        o = ['if', [comparator, '_l', '_r'], '_r', '_l']
        otyp = left.typ
        otyp.is_literal = False
    elif _can_compare_with_uint256(left) and _can_compare_with_uint256(right):
        o = ['if', [comparator, '_l', '_r'], '_r', '_l']
        if right.typ.typ == 'uint256':
            otyp = right.typ
        else:
            otyp = left.typ
        otyp.is_literal = False
    else:
        raise TypeMismatchException(
            "Minmax types incompatible: %s %s" % (left.typ.typ, right.typ.typ)
        )
    return LLLnode.from_list(
        ['with', '_l', left, ['with', '_r', right, o]],
        typ=otyp,
        pos=getpos(expr),
    )


@signature('decimal')
def sqrt(expr, args, kwargs, context):
    from vyper.functions.utils import (
        generate_inline_function,
    )
    arg = args[0]
    sqrt_code = """
assert x >= 0.0
z: decimal

if x == 0.0:
    z = 0.0
else:
    z = (x + 1.0) / 2.0
    y: decimal = x

    for i in range(256):
        if z == y:
            break
        y = z
        z = (x / z + z) / 2.0
    """

    x_type = BaseType('decimal')
    placeholder_copy = ['pass']
    # Steal current position if variable is already allocated.
    if arg.value == 'mload':
        new_var_pos = arg.args[0]
    # Other locations need to be copied.
    else:
        new_var_pos = context.new_placeholder(x_type)
        placeholder_copy = ['mstore', new_var_pos, arg]
    # Create input variables.
    variables = {
        'x': VariableRecord(
            name='x',
            pos=new_var_pos,
            typ=x_type,
            mutable=False
        )
    }
    # Generate inline LLL.
    new_ctx, sqrt_lll = generate_inline_function(
        code=sqrt_code,
        variables=variables,
        memory_allocator=context.memory_allocator
    )
    return LLLnode.from_list(
        [
            'seq_unchecked',
            placeholder_copy,  # load x variable
            sqrt_lll,
            ['mload', new_ctx.vars['z'].pos]  # unload z variable into the stack,
        ],
        typ=BaseType('decimal'),
        pos=getpos(expr),
    )


def _clear():
    raise ParserException(
        "This function should never be called! `clear()` is currently handled "
        "differently than other functions as it self modifies its input argument "
        "statement. Please see `_clear()` in `stmt.py`"
    )


dispatch_table = {
    'floor': floor,
    'ceil': ceil,
    'as_unitless_number': as_unitless_number,
    'convert': _convert,
    'slice': _slice,
    'len': _len,
    'concat': concat,
    'sha3': _sha3,
    'sha256': sha256,
    'method_id': method_id,
    'keccak256': _sha3,
    'ecrecover': ecrecover,
    'ecadd': ecadd,
    'ecmul': ecmul,
    'extract32': extract32,
    'as_wei_value': as_wei_value,
    'raw_call': raw_call,
    'RLPList': _RLPlist,
    'blockhash': blockhash,
    'bitwise_and': bitwise_and,
    'bitwise_or': bitwise_or,
    'bitwise_xor': bitwise_xor,
    'bitwise_not': bitwise_not,
    'uint256_addmod': uint256_addmod,
    'uint256_mulmod': uint256_mulmod,
    'sqrt': sqrt,
    'shift': shift,
    'create_forwarder_to': create_forwarder_to,
    'min': _min,
    'max': _max,
}

stmt_dispatch_table = {
    'clear': _clear,
    'send': send,
    'selfdestruct': selfdestruct,
    'raw_call': raw_call,
    'raw_log': raw_log,
    'create_forwarder_to': create_forwarder_to,
}

built_in_functions = [
    x for x in stmt_dispatch_table.keys()
] + [
    x for x in dispatch_table.keys()
]
