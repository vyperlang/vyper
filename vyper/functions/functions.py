from decimal import (
    Decimal,
)
import hashlib

from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    ArgumentException,
    ConstancyViolation,
    InvalidLiteral,
    StructureException,
    TypeMismatch,
)
from vyper.opcodes import (
    version_check,
)
from vyper.parser.expr import (
    Expr,
)
from vyper.parser.keccak256_helper import (
    keccak256_helper,
)
from vyper.parser.parser_utils import (
    LLLnode,
    add_variable_offset,
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
    is_base_type,
)
from vyper.types.convert import (
    convert,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    MemoryPositions,
    SizeLimits,
    bytes_to_int,
    fourbytes_to_int,
    keccak256,
)

from .signatures import (
    Optional,
    signature,
    validate_inputs,
)

SHA256_ADDRESS = 2
SHA256_BASE_GAS = 60
SHA256_PER_WORD_GAS = 12


def get_keyword(expr, keyword):
    for kw in expr.keywords:
        if kw.arg == keyword:
            return kw.value
    # This should never happen, as kwargs['value'] will KeyError first.
    # Leaving exception for other use cases.
    raise Exception(f"Keyword {keyword} not found")  # pragma: no cover


# currently no option for reason string (easy to add, just need to refactor
# vyper.parser.stmt so we can use _assert_reason).
class AssertModifiable:
    """
    Assert a condition without performing a constancy check.
    """
    _id = "assert_modifiable"
    _inputs = [("cond", "bool")]
    _return_type = None

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(['assert', args[0]], typ=None, pos=getpos(expr))


class Floor:

    _id = "floor"
    _inputs = [("value", "decimal")]
    _return_type = "int128"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            [
                'if',
                ['slt', args[0], 0],
                ['sdiv', ['sub', args[0], DECIMAL_DIVISOR - 1], DECIMAL_DIVISOR],
                ['sdiv', args[0], DECIMAL_DIVISOR]
            ],
            typ=BaseType('int128'),
            pos=getpos(expr)
        )


class Ceil:

    _id = "ceil"
    _inputs = [("value", "decimal")]
    _return_type = "int128"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            [
                'if',
                ['slt', args[0], 0],
                ['sdiv', args[0], DECIMAL_DIVISOR],
                ['sdiv', ['add', args[0], DECIMAL_DIVISOR - 1], DECIMAL_DIVISOR]
            ],
            typ=BaseType('int128'),
            pos=getpos(expr)
        )


def _convert(expr, context):
    return convert(expr, context)


class Slice:

    _id = "slice"
    _inputs = [("b", ('bytes', 'bytes32', 'string')), ('start', 'int128'), ('length', 'int128')]
    _return_type = None

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):

        sub, start, length = args
        if is_base_type(sub.typ, 'bytes32'):
            if (
                (start.typ.is_literal and length.typ.is_literal) and
                not (0 <= start.value + length.value <= 32)
            ):
                raise InvalidLiteral(
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
        return LLLnode.from_list(
            out, typ=ReturnType(newmaxlen), location='memory', pos=getpos(expr)
        )


class Len:

    _id = "len"
    _inputs = [("b", ("bytes", "string"))]
    _return_type = "int128"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return get_length(args[0])


def concat(expr, context):
    args = [Expr(arg, context).lll_node for arg in expr.args]
    if len(args) < 2:
        raise StructureException("Concat expects at least two arguments", expr)

    prev_type = ''
    for _, (expr_arg, arg) in enumerate(zip(expr.args, args)):
        if not isinstance(arg.typ, ByteArrayLike) and not is_base_type(arg.typ, 'bytes32'):
            raise TypeMismatch("Concat expects string, bytes or bytes32 objects", expr_arg)

        current_type = (
            'bytes'
            if isinstance(arg.typ, ByteArrayType) or is_base_type(arg.typ, 'bytes32')
            else 'string'
        )
        if prev_type and current_type != prev_type:
            raise TypeMismatch(
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
        arg.typ.maxlen if isinstance(arg.typ, ByteArrayLike) else 32 for arg in args
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
    raise StructureException("sha3 function has been deprecated in favor of keccak256")


@signature(('bytes_literal', 'str_literal', 'bytes', 'string', 'bytes32'))
def _keccak256(expr, args, kwargs, context):
    return keccak256_helper(expr, args, kwargs, context)


def _make_sha256_call(inp_start, inp_len, out_start, out_len):
    return [
        'assert', [
            'staticcall',
            ['gas'],  # gas
            SHA256_ADDRESS,  # address
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
        raise Exception(f"Unsupported location: {sub.location}")  # pragma: no test


@signature('str_literal', 'name_literal')
def method_id(expr, args, kwargs, context):
    if b' ' in args[0]:
        raise TypeMismatch('Invalid function signature no spaces allowed.')
    method_id = fourbytes_to_int(keccak256(args[0])[:4])
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


class ECRecover:

    _id = "ecrecover"
    _inputs = [("hash", "bytes32"), ("v", "uint256"), ("r", "uint256"), ("s", "uint256")]
    _return_type = "address"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        placeholder_node = LLLnode.from_list(
            context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
        )
        return LLLnode.from_list([
            'seq',
            ['mstore', placeholder_node, args[0]],
            ['mstore', ['add', placeholder_node, 32], args[1]],
            ['mstore', ['add', placeholder_node, 64], args[2]],
            ['mstore', ['add', placeholder_node, 96], args[3]],
            ['pop', [
                'staticcall', ['gas'], 1, placeholder_node, 128, MemoryPositions.FREE_VAR_SPACE, 32
            ]],
            ['mload', MemoryPositions.FREE_VAR_SPACE],
        ], typ=BaseType('address'), pos=getpos(expr))


def avo(arg, ind, pos):
    return unwrap_location(add_variable_offset(arg, LLLnode.from_list(ind, 'int128'), pos=pos))


class ECAdd:

    _id = "ecadd"
    _inputs = [("a", "uint256[2]"), ("b", "uint256[2]")]
    _return_type = "uint256[2]"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
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
            ['assert', ['staticcall', ['gas'], 6, placeholder_node, 128, placeholder_node, 64]],
            placeholder_node,
        ], typ=ListType(BaseType('uint256'), 2), pos=getpos(expr), location='memory')
        return o


class ECMul:

    _id = "ecmul"
    _inputs = [("point", "uint256[2]"), ("scalar", "uint256")]
    _return_type = "uint256[2]"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        placeholder_node = LLLnode.from_list(
            context.new_placeholder(ByteArrayType(128)), typ=ByteArrayType(128), location='memory'
        )
        pos = getpos(expr)
        o = LLLnode.from_list([
            'seq',
            ['mstore', placeholder_node, avo(args[0], 0, pos)],
            ['mstore', ['add', placeholder_node, 32], avo(args[0], 1, pos)],
            ['mstore', ['add', placeholder_node, 64], args[1]],
            ['assert', ['staticcall', ['gas'], 7, placeholder_node, 96, placeholder_node, 64]],
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
    wei_denominations = {
        ("wei", ): 1,
        ("femtoether", "kwei", "babbage"): 10**3,
        ("picoether", "mwei", "lovelace"): 10**6,
        ("nanoether", "gwei", "shannon"): 10**9,
        ("microether", "szabo", ): 10**12,
        ("milliether", "finney", ): 10**15,
        ("ether", ): 10**18,
        ("kether", "grand"): 10**21,
    }

    value, denom_name = args[0], args[1].decode()

    denom_divisor = next((v for k, v in wei_denominations.items() if denom_name in k), False)
    if not denom_divisor:
        raise InvalidLiteral(
            f"Invalid denomination: {denom_name}, valid denominations are: "
            f"{','.join(x[0] for x in wei_denominations)}",
            expr.args[1]
        )

    # Compute the amount of wei and return that value
    if isinstance(value, (int, Decimal)):
        expr_args_0 = expr.args[0]
        # On constant reference fetch value node of constant assignment.
        if context.constants.ast_is_constant(expr.args[0]):
            expr_args_0 = context.constants._constants_ast[expr.args[0].id]
        numstring, num, den = get_number_as_fraction(expr_args_0, context)
        if denom_divisor % den:
            max_len = len(str(denom_divisor))-1
            raise InvalidLiteral(
                f"Wei value of denomination '{denom_name}' has maximum {max_len} decimal places",
                expr.args[0]
            )
        sub = num * denom_divisor // den
    elif value.typ.is_literal:
        if value.value <= 0:
            raise InvalidLiteral("Negative wei value not allowed", expr)
        sub = ['mul', value.value, denom_divisor]
    elif value.typ.typ == 'uint256':
        sub = ['mul', value, denom_divisor]
    else:
        sub = ['div', ['mul', value, denom_divisor], DECIMAL_DIVISOR]

    return LLLnode.from_list(
        sub,
        typ=BaseType('uint256'),
        location=None,
        pos=getpos(expr),
    )


zero_value = LLLnode.from_list(0, typ=BaseType('uint256'))
false_value = LLLnode.from_list(0, typ=BaseType('bool', is_literal=True))


class RawCall:

    _id = "raw_call"
    _inputs = [("to", "address"), ("data", "bytes")]
    _kwargs = {
        "outsize": Optional('num_literal', 0),
        "gas": Optional('uint256', 'gas'),
        "value": Optional('uint256', zero_value),
        "is_delegate_call": Optional('bool', false_value),
    }
    _return_type = None

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        to, data = args
        gas, value, outsize, delegate_call = (
            kwargs['gas'],
            kwargs['value'],
            kwargs['outsize'],
            kwargs['is_delegate_call'],
        )
        if delegate_call.typ.is_literal is False:
            raise TypeMismatch(
                'The delegate_call parameter has to be a static/literal boolean value.'
            )
        if context.is_constant():
            raise ConstancyViolation(
                f"Cannot make calls from {context.pp_constancy()}",
                expr,
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

        # build LLL for call or delegatecall
        common_call_lll = [
            ['add', placeholder_node, 32],
            ['mload', placeholder_node],
            # if there is no return value, the return offset can be 0
            ['add', output_node, 32] if outsize else 0,
            outsize
        ]

        if delegate_call.value == 1:
            call_lll = ['delegatecall', gas, to] + common_call_lll
        else:
            call_lll = ['call', gas, to, value] + common_call_lll

        # build sequence LLL
        if outsize:
            # only copy the return value to memory if outsize > 0
            seq = [
                'seq', copier, ['assert', call_lll], ['mstore', output_node, outsize], output_node
            ]
            typ = ByteArrayType(outsize)
        else:
            seq = ['seq', copier, ['assert', call_lll]]
            typ = None

        return LLLnode.from_list(seq, typ=typ, location="memory", pos=getpos(expr))


class Send:

    _id = "send"
    _inputs = [("to", "address"), ("value", "uint256")]
    _return_type = None

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        to, value = args
        if context.is_constant():
            raise ConstancyViolation(
                f"Cannot send ether inside {context.pp_constancy()}!",
                expr,
            )
        return LLLnode.from_list(
            ['assert', ['call', 0, to, value, 0, 0, 0, 0]],
            typ=None,
            pos=getpos(expr),
        )


class SelfDestruct:

    _id = "selfdestruct"
    _inputs = [("to", "address")]
    _return_type = None

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        if context.is_constant():
            raise ConstancyViolation(
                f"Cannot {expr.func.id} inside {context.pp_constancy()}!",
                expr.func,
            )
        return LLLnode.from_list(['selfdestruct', args[0]], typ=None, pos=getpos(expr))


class BlockHash:

    _id = "blockhash"
    _inputs = [("block_num", "uint256")]
    _return_type = "bytes32"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, contact):
        return LLLnode.from_list(
            ['blockhash', ['uclamplt', ['clampge', args[0], ['sub', ['number'], 256]], 'number']],
            typ=BaseType('bytes32'),
            pos=getpos(expr),
        )


@signature('*', ('bytes32', 'bytes'))
def raw_log(expr, args, kwargs, context):
    if not isinstance(args[0], vy_ast.List) or len(args[0].elts) > 4:
        raise StructureException("Expecting a list of 0-4 topics as first argument", args[0])
    topics = []
    for elt in args[0].elts:
        arg = Expr.parse_value_expr(elt, context)
        if not is_base_type(arg.typ, 'bytes32'):
            raise TypeMismatch("Expecting a bytes32 argument as topic", elt)
        topics.append(arg)
    if args[1].typ == BaseType('bytes32'):
        placeholder = context.new_placeholder(BaseType('bytes32'))
        return LLLnode.from_list(
            ['seq',
                ['mstore', placeholder, unwrap_location(args[1])],
                [
                    "log" + str(len(topics)),
                    placeholder,
                    32,
                ] + topics], typ=None, pos=getpos(expr))
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


class BitwiseAnd:

    _id = "bitwise_and"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            ['and', args[0], args[1]], typ=BaseType('uint256'), pos=getpos(expr)
        )


class BitwiseNot:

    _id = "bitwise_not"
    _inputs = [("x", "uint256")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(['not', args[0]], typ=BaseType('uint256'), pos=getpos(expr))


class BitwiseOr:

    _id = "bitwise_or"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            ['or', args[0], args[1]], typ=BaseType('uint256'), pos=getpos(expr)
        )


class BitwiseXor:

    _id = "bitwise_xor"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            ['xor', args[0], args[1]], typ=BaseType('uint256'), pos=getpos(expr)
        )


class AddMod:

    _id = "uint256_addmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            [
                'seq',
                ['assert', args[2]],
                ['addmod', args[0], args[1], args[2]],
            ],
            typ=BaseType('uint256'),
            pos=getpos(expr),
        )


class MulMod:

    _id = "uint256_mulmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return LLLnode.from_list(
            [
                'seq',
                ['assert', args[2]],
                ['mulmod', args[0], args[1], args[2]],
            ],
            typ=BaseType('uint256'),
            pos=getpos(expr),
        )


class Shift:

    _id = "shift"
    _inputs = [("x", "uint256"), ("_shift", "int128")]
    _return_type = "uint256"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        if args[1].typ.is_literal:
            shift_abs = abs(args[1].value)
        else:
            shift_abs = ['sub', 0, '_s']

        if version_check(begin="constantinople"):
            left_shift = ['shl', '_s', '_v']
            right_shift = ['shr', shift_abs, '_v']
        else:
            # If second argument is positive, left-shift so multiply by a power of two
            # If it is negative, divide by a power of two
            # node that if the abs of the second argument >= 256, then in the EVM
            # 2**(second arg) = 0, and multiplying OR dividing by 0 gives 0
            left_shift = ['mul', '_v', ['exp', 2, '_s']]
            right_shift = ['div', '_v', ['exp', 2, shift_abs]]

        if not args[1].typ.is_literal:
            node_list = ['if', ['slt', '_s', 0], right_shift, left_shift]
        elif args[1].value >= 0:
            node_list = left_shift
        else:
            node_list = right_shift

        return LLLnode.from_list(
            [
                'with', '_v', args[0], [
                    'with', '_s', args[1],
                        node_list,
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


class CreateForwarderTo:

    _id = "create_forwarder_to"
    _inputs = [("target", "address")]
    _kwargs = {'value': Optional('uint256', zero_value)}
    _return_type = "address"

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        value = kwargs['value']
        if context.is_constant():
            raise ConstancyViolation(
                f"Cannot make calls from {context.pp_constancy()}",
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


class Min:

    _id = "min"
    _inputs = [("a", ('int128', 'decimal', 'uint256')), ("b", ('int128', 'decimal', 'uint256'))]

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return minmax(expr, args, kwargs, context, 'gt')


class Max:

    _id = "max"
    _inputs = [("a", ('int128', 'decimal', 'uint256')), ("b", ('int128', 'decimal', 'uint256'))]

    @validate_inputs
    def build_LLL(self, expr, args, kwargs, context):
        return minmax(expr, args, kwargs, context, 'lt')


def minmax(expr, args, kwargs, context, comparator):
    def _can_compare_with_uint256(operand):
        if operand.typ.typ == 'uint256':
            return True
        elif operand.typ.typ == 'int128' and operand.typ.is_literal and SizeLimits.in_bounds('uint256', operand.value):  # noqa: E501
            return True
        return False

    left, right = args[0], args[1]
    if left.typ.typ == right.typ.typ:
        if left.typ.typ != 'uint256':
            # if comparing like types that are not uint256, use SLT or SGT
            comparator = f's{comparator}'
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
        raise TypeMismatch(
            f"Minmax types incompatible: {left.typ.typ} {right.typ.typ}"
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
z: decimal = 0.0

if x == 0.0:
    z = 0.0
else:
    z = x / 2.0 + 0.5
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


def empty(expr, context):
    if len(expr.args) != 1:
        raise ArgumentException('function expects two parameters.', expr)
    output_type = context.parse_type(expr.args[0], expr.args[0])
    return LLLnode(None, typ=output_type, pos=getpos(expr))


DISPATCH_TABLE = {
    'floor': Floor().build_LLL,
    'ceil': Ceil().build_LLL,
    'convert': _convert,
    'slice': Slice().build_LLL,
    'len': Len().build_LLL,
    'concat': concat,
    'sha3': _sha3,
    'sha256': sha256,
    'method_id': method_id,
    'keccak256': _keccak256,
    'ecrecover': ECRecover().build_LLL,
    'ecadd': ECAdd().build_LLL,
    'ecmul': ECMul().build_LLL,
    'extract32': extract32,
    'as_wei_value': as_wei_value,
    'raw_call': RawCall().build_LLL,
    'blockhash': BlockHash().build_LLL,
    'bitwise_and': BitwiseAnd().build_LLL,
    'bitwise_or': BitwiseOr().build_LLL,
    'bitwise_xor': BitwiseXor().build_LLL,
    'bitwise_not': BitwiseNot().build_LLL,
    'uint256_addmod': AddMod().build_LLL,
    'uint256_mulmod': MulMod().build_LLL,
    'sqrt': sqrt,
    'shift': Shift().build_LLL,
    'create_forwarder_to': CreateForwarderTo().build_LLL,
    'min': Min().build_LLL,
    'max': Max().build_LLL,
    'empty': empty,
}

STMT_DISPATCH_TABLE = {
    'assert_modifiable': AssertModifiable().build_LLL,
    'send': Send().build_LLL,
    'selfdestruct': SelfDestruct().build_LLL,
    'raw_call': RawCall().build_LLL,
    'raw_log': raw_log,
    'create_forwarder_to': CreateForwarderTo().build_LLL,
}

BUILTIN_FUNCTIONS = {**STMT_DISPATCH_TABLE, **DISPATCH_TABLE}.keys()
