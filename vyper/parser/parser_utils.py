import ast as python_ast
from typing import (
    Any,
    List,
    Optional,
    Union,
)

from vyper import ast
from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ListType,
    MappingType,
    NullType,
    StringType,
    StructType,
    TupleLike,
    TupleType,
    are_units_compatible,
    ceil32,
    get_size_of_type,
    has_dynamic_data,
    is_base_type,
)
from vyper.types.types import (
    ContractType,
)
from vyper.typing import (
    ClassTypes,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    GAS_IDENTITY,
    GAS_IDENTITYWORD,
    MemoryPositions,
    SizeLimits,
)


# Get a decimal number as a fraction with denominator multiple of 10
def get_number_as_fraction(expr, context):
    context_slice = context.origcode.splitlines()[expr.lineno - 1][expr.col_offset:]
    t = 0
    while t < len(context_slice) and context_slice[t] in '0123456789.':
        t += 1
    top = int(context_slice[:t].replace('.', ''))
    bottom = 1 if '.' not in context_slice[:t] else 10**(t - context_slice[:t].index('.') - 1)

    if expr.n < 0:
        top *= -1

    return context_slice[:t], top, bottom


# Is a number of decimal form (e.g. 65281) or 0x form (e.g. 0xff01) or 0b binary form (e.g. 0b0001)
def get_original_if_0_prefixed(expr, context):
    context_slice = context.origcode.splitlines()[expr.lineno - 1][expr.col_offset:]
    type_prefix = context_slice[:2]

    if type_prefix not in ('0x', '0b'):
        return None

    if type_prefix == '0x':
        t = 0
        while t + 2 < len(context_slice) and context_slice[t + 2] in '0123456789abcdefABCDEF':
            t += 1
        return context_slice[:t + 2]
    elif type_prefix == '0b':
        t = 0
        while t + 2 < len(context_slice) and context_slice[t + 2] in '01':
            t += 1
        return context_slice[:t + 2]


# Copies byte array
def make_byte_array_copier(destination, source, pos=None):
    if not isinstance(source.typ, (ByteArrayLike, NullType)):
        btype = 'byte array' if isinstance(destination.typ, ByteArrayType) else 'string'
        raise TypeMismatchException("Can only set a {} to another {}".format(btype, btype), pos)
    if isinstance(source.typ, ByteArrayLike) and source.typ.maxlen > destination.typ.maxlen:
        raise TypeMismatchException(
            "Cannot cast from greater max-length %d to shorter max-length %d" % (
                source.typ.maxlen,
                destination.typ.maxlen,
            ))
    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        gas_calculation = GAS_IDENTITY + GAS_IDENTITYWORD * (ceil32(source.typ.maxlen) // 32)
        o = LLLnode.from_list([
            'with', '_source', source, [
                'with', '_sz', ['add', 32, ['mload', '_source']], [
                    'assert', ['call', ['add', 18, ['div', '_sz', 10]], 4, 0, '_source', '_sz', destination, '_sz']]]],  # noqa: E501
            typ=None, add_gas_estimate=gas_calculation, annotation='Memory copy'
        )
        return o

    pos_node = LLLnode.from_list('_pos', typ=source.typ, location=source.location)
    # Get the length
    if isinstance(source.typ, NullType):
        length = 1
    elif source.location == "memory":
        length = ['add', ['mload', '_pos'], 32]
    elif source.location == "storage":
        length = ['add', ['sload', '_pos'], 32]
        pos_node = LLLnode.from_list(
            ['sha3_32', pos_node],
            typ=source.typ,
            location=source.location,
        )
    else:
        raise Exception("Unsupported location:" + source.location)
    if destination.location == "storage":
        destination = LLLnode.from_list(
            ['sha3_32', destination],
            typ=destination.typ,
            location=destination.location,
        )
    # Maximum theoretical length
    max_length = 32 if isinstance(source.typ, NullType) else source.typ.maxlen + 32
    return LLLnode.from_list([
        'with', '_pos',
        0 if isinstance(source.typ, NullType) else source,
        make_byte_slice_copier(destination, pos_node, length, max_length, pos=pos)
    ], typ=None)


# Copy bytes
# Accepts 4 arguments:
# (i) an LLL node for the start position of the source
# (ii) an LLL node for the start position of the destination
# (iii) an LLL node for the length
# (iv) a constant for the max length
def make_byte_slice_copier(destination, source, length, max_length, pos=None):
    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        return LLLnode.from_list([
            'with', '_l', max_length,
            [
                'pop',
                ['call', 18 + max_length // 10, 4, 0, source, '_l', destination, '_l']
            ]
        ], typ=None, annotation='copy byte slice dest: %s' % str(destination))
    # Copy over data
    if isinstance(source.typ, NullType):
        loader = 0
    elif source.location == "memory":
        loader = ['mload', ['add', '_pos', ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]]]
    elif source.location == "storage":
        loader = ['sload', ['add', '_pos', ['mload', MemoryPositions.FREE_LOOP_INDEX]]]
    else:
        raise Exception("Unsupported location:" + source.location)
    # Where to paste it?
    if destination.location == "memory":
        setter = [
            'mstore',
            ['add', '_opos', ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]],
            loader
        ]
    elif destination.location == "storage":
        setter = ['sstore', ['add', '_opos', ['mload', MemoryPositions.FREE_LOOP_INDEX]], loader]
    else:
        raise Exception("Unsupported location:" + destination.location)
    # Check to see if we hit the length
    checker = [
        'if',
        ['gt', ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]], '_actual_len'],
        'break'
    ]
    # Make a loop to do the copying
    o = [
        'with', '_pos', source, [
            'with', '_opos', destination, [
                'with', '_actual_len', length, [
                    'repeat',
                    MemoryPositions.FREE_LOOP_INDEX,
                    0,
                    (max_length + 31) // 32,
                    ['seq', checker, setter]
                ]
            ]
        ]
    ]
    return LLLnode.from_list(
        o,
        typ=None,
        annotation='copy byte slice src: %s dst: %s' % (source, destination),
        pos=pos,
    )


# Takes a <32 byte array as input, and outputs a number.
def byte_array_to_num(arg, expr, out_type, offset=32,):
    if arg.location == "memory":
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('int128'))
        first_el_getter = LLLnode.from_list(['mload', ['add', 32, '_sub']], typ=BaseType('int128'))
    elif arg.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('int128'))
        first_el_getter = LLLnode.from_list([
            'sload', ['add', 1, ['sha3_32', '_sub']]
        ], typ=BaseType('int128'))
    if out_type == 'int128':
        result = [
            'clamp',
            ['mload', MemoryPositions.MINNUM],
            ['div', '_el1', ['exp', 256, ['sub', 32, '_len']]],
            ['mload', MemoryPositions.MAXNUM]
        ]
    elif out_type == 'uint256':
        result = ['div', '_el1', ['exp', 256, ['sub', offset, '_len']]]
    return LLLnode.from_list([
        'with', '_sub', arg, [
            'with', '_el1', first_el_getter, [
                'with', '_len', [
                    'clamp', 0, lengetter, 32
                ],
                result,
            ]
        ]
    ], typ=BaseType(out_type), annotation='bytearray to number (%s)' % out_type)


def get_length(arg):
    if arg.location == "memory":
        return LLLnode.from_list(['mload', arg], typ=BaseType('int128'))
    elif arg.location == "storage":
        return LLLnode.from_list(['sload', ['sha3_32', arg]], typ=BaseType('int128'))


def getpos(node):
    return (node.lineno, node.col_offset)


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
def add_variable_offset(parent, key, pos):
    typ, location = parent.typ, parent.location
    if isinstance(typ, (StructType, TupleType)):
        if isinstance(typ, StructType):
            if not isinstance(key, str):
                raise TypeMismatchException(
                    "Expecting a member variable access; cannot access element %r" % key, pos
                )
            if key not in typ.members:
                raise TypeMismatchException("Object does not have member variable %s" % key, pos)
            subtype = typ.members[key]
            attrs = list(typ.members.keys())

            if key not in attrs:
                raise TypeMismatchException(
                    "Member %s not found. Only the following available: %s" % (
                        key,
                        " ".join(attrs)
                    ),
                    pos
                )
            index = attrs.index(key)
            annotation = key
        else:
            if not isinstance(key, int):
                raise TypeMismatchException(
                    "Expecting a static index; cannot access element %r" % key, pos
                )
            attrs = list(range(len(typ.members)))
            index = key
            annotation = None
        if location == 'storage':
            return LLLnode.from_list(
                ['add', ['sha3_32', parent], LLLnode.from_list(index, annotation=annotation)],
                typ=subtype,
                location='storage',
            )
        elif location == 'storage_prehashed':
            return LLLnode.from_list(
                ['add', parent, LLLnode.from_list(index, annotation=annotation)],
                typ=subtype,
                location='storage',
            )
        elif location == 'memory':
            offset = 0
            for i in range(index):
                offset += 32 * get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(['add', offset, parent],
                                     typ=typ.members[key],
                                     location='memory',
                                     annotation=annotation)
        else:
            raise TypeMismatchException("Not expecting a member variable access", pos)

    elif isinstance(typ, MappingType):

        if isinstance(key.typ, ByteArrayLike):
            if not isinstance(typ.keytype, ByteArrayLike) or (typ.keytype.maxlen < key.typ.maxlen):
                raise TypeMismatchException(
                    'Mapping keys of bytes cannot be cast, use exact same bytes type of: %s' % (
                        str(typ.keytype),
                    ),
                    pos,
                )
            subtype = typ.valuetype
            if len(key.args[0].args) >= 3:  # handle bytes literal.
                sub = LLLnode.from_list([
                    'seq',
                    key,
                    ['sha3', ['add', key.args[0].args[-1], 32], ['mload', key.args[0].args[-1]]]
                ])
            else:
                sub = LLLnode.from_list(
                    ['sha3', ['add', key.args[0].value, 32], ['mload', key.args[0].value]]
                )
        else:
            subtype = typ.valuetype
            sub = base_type_conversion(key, key.typ, typ.keytype, pos=pos)

        if location == 'storage':
            return LLLnode.from_list(['sha3_64', parent, sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            raise TypeMismatchException(
                "Can only have fixed-side arrays in memory, not mappings", pos
            )

    elif isinstance(typ, ListType):

        subtype = typ.subtype
        sub = [
            'uclamplt', base_type_conversion(key, key.typ, BaseType('int128'), pos=pos), typ.count
        ]

        if location == 'storage':
            return LLLnode.from_list(['add', ['sha3_32', parent], sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'storage_prehashed':
            return LLLnode.from_list(['add', parent, sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            offset = 32 * get_size_of_type(subtype)
            return LLLnode.from_list(
                ['add', ['mul', offset, sub], parent],
                typ=subtype,
                location='memory',
            )
        else:
            raise TypeMismatchException("Not expecting an array access ", pos)
    else:
        raise TypeMismatchException("Cannot access the child of a constant variable! %r" % typ, pos)


# Convert from one base type to another
def base_type_conversion(orig, frm, to, pos, in_function_call=False):
    orig = unwrap_location(orig)
    is_valid_int128_to_decimal = (
        is_base_type(frm, 'int128') and is_base_type(to, 'decimal')
    ) and are_units_compatible(frm, to)

    if getattr(frm, 'is_literal', False) and frm.typ in ('int128', 'uint256'):
        if not SizeLimits.in_bounds(frm.typ, orig.value):
            raise InvalidLiteralException("Number out of range: " + str(orig.value), pos)
        # Special Case: Literals in function calls should always convey unit type as well.
        if in_function_call and not (frm.unit == to.unit and frm.positional == to.positional):
            raise InvalidLiteralException(
                "Function calls require explicit unit definitions on calls, expected %r" % to, pos
            )
    if not isinstance(frm, (BaseType, NullType)) or not isinstance(to, BaseType):
        raise TypeMismatchException(
            "Base type conversion from or to non-base type: %r %r" % (frm, to), pos
        )
    elif is_base_type(frm, to.typ) and are_units_compatible(frm, to):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    elif isinstance(frm, ContractType) and to == BaseType('address'):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    elif is_valid_int128_to_decimal:
        return LLLnode.from_list(
            ['mul', orig, DECIMAL_DIVISOR],
            typ=BaseType('decimal', to.unit, to.positional),
        )
    elif isinstance(frm, NullType):
        if to.typ not in ('int128', 'bool', 'uint256', 'address', 'bytes32', 'decimal'):
            # This is only to future proof the use of  base_type_conversion.
            raise TypeMismatchException(  # pragma: no cover
                "Cannot convert null-type object to type %r" % to, pos
            )
        return LLLnode.from_list(0, typ=to)
    # Integer literal conversion.
    elif (frm.typ, to.typ, frm.is_literal) == ('int128', 'uint256', True):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    else:
        raise TypeMismatchException(
            "Typecasting from base type %r to %r unavailable" % (frm, to), pos
        )


# Unwrap location
def unwrap_location(orig):
    if orig.location == 'memory':
        return LLLnode.from_list(['mload', orig], typ=orig.typ)
    elif orig.location == 'storage':
        return LLLnode.from_list(['sload', orig], typ=orig.typ)
    else:
        return orig


# Pack function arguments for a call
def pack_arguments(signature, args, context, pos, return_placeholder=True):
    placeholder_typ = ByteArrayType(
        maxlen=sum([get_size_of_type(arg.typ) for arg in signature.args]) * 32 + 32
    )
    placeholder = context.new_placeholder(placeholder_typ)
    setters = [['mstore', placeholder, signature.method_id]]
    needpos = False
    staticarray_offset = 0
    expected_arg_count = len(signature.args)
    actual_arg_count = len(args)
    if actual_arg_count != expected_arg_count:
        raise StructureException(
            "Wrong number of args for: %s (%s args, expected %s)" % (
                signature.name,
                actual_arg_count,
                expected_arg_count,
            )
        )

    for i, (arg, typ) in enumerate(zip(args, [arg.typ for arg in signature.args])):
        if isinstance(typ, BaseType):
            setters.append(make_setter(LLLnode.from_list(
                placeholder + staticarray_offset + 32 + i * 32,
                typ=typ,
            ), arg, 'memory', pos=pos, in_function_call=True))

        elif isinstance(typ, ByteArrayLike):
            setters.append(['mstore', placeholder + staticarray_offset + 32 + i * 32, '_poz'])
            arg_copy = LLLnode.from_list('_s', typ=arg.typ, location=arg.location)
            target = LLLnode.from_list(
                ['add', placeholder + 32, '_poz'],
                typ=typ,
                location='memory',
            )
            setters.append([
                'with', '_s', arg, [
                    'seq',
                    make_byte_array_copier(target, arg_copy, pos),
                    [
                        'set',
                        '_poz',
                        ['add', 32, ['ceil32', ['add', '_poz', get_length(arg_copy)]]]
                    ],
                ],
            ])
            needpos = True

        elif isinstance(typ, (StructType, ListType)):
            if has_dynamic_data(typ):
                raise TypeMismatchException("Cannot pack bytearray in struct")
            target = LLLnode.from_list(
                [placeholder + 32 + staticarray_offset + i * 32],
                typ=typ,
                location='memory',
            )
            setters.append(make_setter(target, arg, 'memory', pos=pos))
            if (isinstance(typ, ListType)):
                count = typ.count
            else:
                count = len(typ.tuple_items())
            staticarray_offset += 32 * (count - 1)

        else:
            raise TypeMismatchException("Cannot pack argument of type %r" % typ)

    # For private call usage, doesn't use a returner.
    returner = [[placeholder + 28]] if return_placeholder else []
    if needpos:
        return (
            LLLnode.from_list([
                'with',
                '_poz',
                len(args) * 32 + staticarray_offset,
                ['seq'] + setters + returner
            ], typ=placeholder_typ, location='memory'),
            placeholder_typ.maxlen - 28,
            placeholder + 32
        )
    else:
        return (
            LLLnode.from_list(['seq'] + setters + returner, typ=placeholder_typ, location='memory'),
            placeholder_typ.maxlen - 28,
            placeholder + 32
        )


# Create an x=y statement, where the types may be compound
def make_setter(left, right, location, pos, in_function_call=False):
    # Basic types
    if isinstance(left.typ, BaseType):
        right = base_type_conversion(
            right,
            right.typ,
            left.typ,
            pos,
            in_function_call=in_function_call,
        )
        if location == 'storage':
            return LLLnode.from_list(['sstore', left, right], typ=None)
        elif location == 'memory':
            return LLLnode.from_list(['mstore', left, right], typ=None)
    # Byte arrays
    elif isinstance(left.typ, ByteArrayLike):
        return make_byte_array_copier(left, right, pos)
    # Can't copy mappings
    elif isinstance(left.typ, MappingType):
        raise TypeMismatchException("Cannot copy mappings; can only copy individual elements", pos)
    # Arrays
    elif isinstance(left.typ, ListType):
        # Cannot do something like [a, b, c] = [1, 2, 3]
        if left.value == "multi":
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, (ListType, NullType)):
            raise TypeMismatchException(
                "Setter type mismatch: left side is array, right side is %r" % right.typ, pos
            )
        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        # Type checks
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, ListType):
                raise TypeMismatchException("Left side is array, right side is not", pos)
            if left.typ.count != right.typ.count:
                raise TypeMismatchException("Mismatched number of elements", pos)
        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != left.typ.count:
                raise TypeMismatchException("Mismatched number of elements", pos)
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(
                    left_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                ), right.args[i], location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        elif isinstance(right.typ, NullType):
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(
                    left_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                ), LLLnode.from_list(None, typ=NullType()), location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a variable
        else:
            right_token = LLLnode.from_list('_R', typ=right.typ, location=right.location)
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(
                    left_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                ), add_variable_offset(
                    right_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                ), location, pos=pos))
            return LLLnode.from_list([
                'with', '_L', left, [
                    'with', '_R', right, ['seq'] + subs]
            ], typ=None)
    # Structs
    elif isinstance(left.typ, (StructType, TupleType)):
        if left.value == "multi" and isinstance(left.typ, StructType):
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, left.typ.__class__):
                raise TypeMismatchException(
                    "Setter type mismatch: left side is %r, right side is %r" % (
                        left.typ,
                        right.typ,
                    ),
                    pos,
                )
            if isinstance(left.typ, StructType):
                for k in right.args:
                    if k.value is None:
                        raise InvalidLiteralException(
                            'Setting struct value to None is not allowed, use a default value.',
                            pos,
                        )
                for k in left.typ.members:
                    if k not in right.typ.members:
                        raise TypeMismatchException(
                            "Keys don't match for structs, missing %s" % k,
                            pos,
                        )
                for k in right.typ.members:
                    if k not in left.typ.members:
                        raise TypeMismatchException(
                            "Keys don't match for structs, extra %s" % k,
                            pos,
                        )
                if left.typ.name != right.typ.name:
                    raise TypeMismatchException("Expected %r, got %r" % (left.typ, right.typ), pos)
            else:
                if len(left.typ.members) != len(right.typ.members):
                    raise TypeMismatchException(
                        "Tuple lengths don't match, %d vs %d" % (
                            len(left.typ.members),
                            len(right.typ.members),
                        ),
                        pos,
                    )

        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        if isinstance(left.typ, StructType):
            keyz = list(left.typ.members.keys())
        else:
            keyz = list(range(len(left.typ.members)))

        # If the left side is a literal
        if left.value == 'multi':
            locations = [arg.location for arg in left.args]
        else:
            locations = [location for _ in keyz]

        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != len(keyz):
                raise TypeMismatchException("Mismatched number of elements", pos)
            subs = []
            for i, (typ, loc) in enumerate(zip(keyz, locations)):
                subs.append(make_setter(
                    add_variable_offset(left_token, typ, pos=pos),
                    right.args[i],
                    loc,
                    pos=pos,
                ))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        elif isinstance(right.typ, NullType):
            subs = []
            for typ, loc in zip(keyz, locations):
                subs.append(make_setter(
                    add_variable_offset(left_token, typ, pos=pos),
                    LLLnode.from_list(None, typ=NullType()),
                    loc,
                    pos=pos,
                ))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If tuple assign.
        elif isinstance(left.typ, TupleType) and isinstance(right.typ, TupleType):
            subs = []
            static_offset_counter = 0
            zipped_components = zip(left.args, right.typ.members, locations)
            for left_arg, right_arg, loc in zipped_components:
                if isinstance(right_arg, ByteArrayLike):
                    RType = ByteArrayType if isinstance(right_arg, ByteArrayType) else StringType
                    offset = LLLnode.from_list(
                        ['add', '_R', ['mload', ['add', '_R', static_offset_counter]]],
                        typ=RType(right_arg.maxlen), location='memory', pos=pos)
                    static_offset_counter += 32
                else:
                    offset = LLLnode.from_list(
                        ['mload', ['add', '_R', static_offset_counter]],
                        typ=right_arg.typ,
                        pos=pos,
                    )
                    static_offset_counter += get_size_of_type(right_arg) * 32
                subs.append(
                    make_setter(
                        left_arg,
                        offset,
                        loc,
                        pos=pos
                    )
                )
            return LLLnode.from_list(
                ['with', '_R', right, ['seq'] + subs],
                typ=None,
                annotation='Tuple assignment',
            )
        # If the right side is a variable
        else:
            subs = []
            right_token = LLLnode.from_list('_R', typ=right.typ, location=right.location)
            for typ, loc in zip(keyz, locations):
                subs.append(make_setter(
                    add_variable_offset(left_token, typ, pos=pos),
                    add_variable_offset(right_token, typ, pos=pos),
                    loc,
                    pos=pos
                ))
            return LLLnode.from_list(
                ['with', '_L', left, ['with', '_R', right, ['seq'] + subs]],
                typ=None,
            )
    else:
        raise Exception("Invalid type for setters")


def is_return_from_function(node: Union[python_ast.AST, List[Any]]) -> bool:
    is_selfdestruct = (
        isinstance(node, python_ast.Expr)
        and isinstance(node.value, python_ast.Call)
        and isinstance(node.value.func, python_ast.Name)
        and node.value.func.id == 'selfdestruct'
    )
    if isinstance(node, python_ast.Return):
        return True
    elif isinstance(node, python_ast.Raise):
        return True
    elif is_selfdestruct:
        return True
    else:
        return False


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _class_types: ClassTypes

    def __init__(self, source_code: str, class_types: Optional[ClassTypes] = None):
        self._source_code: str = source_code
        self.counter: int = 0
        if class_types is not None:
            self._class_types = class_types
        else:
            self._class_types = {}

    def generic_visit(self, node):
        # Decorate every node in the AST with the original source code. This is
        # necessary to facilitate error pretty-printing.
        node.source_code = self._source_code
        node.node_id = self.counter
        self.counter += 1

        return super().generic_visit(node)

    def visit_ClassDef(self, node):
        self.generic_visit(node)

        # Decorate class definitions with their respective class types
        node.class_type = self._class_types.get(node.name)

        return node


class RewriteUnarySubVisitor(python_ast.NodeTransformer):
    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, python_ast.USub) and isinstance(node.operand, python_ast.Num):
            node.operand.n = 0 - node.operand.n
            return node.operand
        else:
            return node


class EnsureSingleExitChecker(python_ast.NodeVisitor):

    def visit_FunctionDef(self, node: python_ast.FunctionDef) -> None:
        self.generic_visit(node)
        self.check_return_body(node, node.body)

    def visit_If(self, node: python_ast.If) -> None:
        self.generic_visit(node)
        self.check_return_body(node, node.body)
        if node.orelse:
            self.check_return_body(node, node.orelse)

    def check_return_body(self, node: python_ast.AST, node_list: List[Any]) -> None:
        return_count = len([n for n in node_list if is_return_from_function(n)])
        if return_count > 1:
            raise StructureException(
                f'Too too many exit statements (return, raise or selfdestruct).',
                node
            )
        # Check for invalid code after returns.
        last_node_pos = len(node_list) - 1
        for idx, n in enumerate(node_list):
            if is_return_from_function(n) and idx < last_node_pos:
                # is not last statement in body.
                raise StructureException(
                    'Exit statement with succeeding code (that will not execute).',
                    node_list[idx + 1]
                )


class UnmatchedReturnChecker(python_ast.NodeVisitor):
    """
    Make sure all return statement are balanced
    (both branches of if statement should have returns statements).
    """

    def visit_FunctionDef(self, node: python_ast.FunctionDef) -> None:
        self.generic_visit(node)
        self.handle_primary_function_def(node)

    def handle_primary_function_def(self,  node: python_ast.FunctionDef) -> None:
        if node.returns and not self.return_check(node.body):
            raise StructureException(
                f'Missing or Unmatched return statements in function "{node.name}". '
                'All control flow statements (like if) need balanced return statements.',
                node
            )

    def return_check(self, node: Union[python_ast.AST, List[Any]]) -> bool:
        if is_return_from_function(node):
            return True
        elif isinstance(node, list):
            return any(self.return_check(stmt) for stmt in node)
        elif isinstance(node, python_ast.If):
            if_body_check = self.return_check(node.body)
            else_body_check = self.return_check(node.orelse)
            if if_body_check and else_body_check:  # both side need to match.
                return True
            else:
                return False
        return False


def annotate_ast(
    parsed_ast: Union[python_ast.AST, python_ast.Module],
    source_code: str,
    class_types: Optional[ClassTypes] = None,
) -> None:
    """
    Performs annotation and optimization on a parsed python AST by doing the
    following:

    * Annotating all AST nodes with the originating source code of the AST
    * Annotating class definition nodes with their original class type
      ("contract" or "struct")
    * Substituting negative values for unary subtractions

    :param parsed_ast: The AST to be annotated and optimized.
    :param source_code: The originating source code of the AST.
    :param class_types: A mapping of class names to original class types.
    :return: The annotated and optmized AST.
    """
    AnnotatingVisitor(source_code, class_types).visit(parsed_ast)
    RewriteUnarySubVisitor().visit(parsed_ast)


def zero_pad(bytez_placeholder, maxlen, context):
    zero_padder = LLLnode.from_list(['pass'])
    if maxlen > 0:
        # Iterator used to zero pad memory.
        zero_pad_i = context.new_placeholder(BaseType('uint256'))
        zero_padder = LLLnode.from_list([
            'repeat', zero_pad_i, ['mload', bytez_placeholder], maxlen, [
                'seq',
                # stay within allocated bounds
                ['if', ['gt', ['mload', zero_pad_i], maxlen], 'break'],
                ['mstore8', ['add', ['add', 32, bytez_placeholder], ['mload', zero_pad_i]], 0]
            ]],
            annotation="Zero pad",
        )
    return zero_padder


# Generate return code for stmt
def make_return_stmt(stmt, context, begin_pos, _size, loop_memory_position=None):
    if context.is_private:
        if loop_memory_position is None:
            loop_memory_position = context.new_placeholder(typ=BaseType('uint256'))

        # Make label for stack push loop.
        label_id = '_'.join([str(x) for x in (context.method_id, stmt.lineno, stmt.col_offset)])
        exit_label = 'make_return_loop_exit_%s' % label_id
        start_label = 'make_return_loop_start_%s' % label_id

        # Push prepared data onto the stack,
        # in reverse order so it can be popped of in order.
        if isinstance(begin_pos, int) and isinstance(_size, int):
            # static values, unroll the mloads instead.
            mloads = [
                ['mload', pos] for pos in range(begin_pos, _size, 32)
            ]
            return ['seq_unchecked'] + mloads + [['jump', ['mload', context.callback_ptr]]]
        else:
            mloads = [
                'seq_unchecked',
                ['mstore', loop_memory_position, _size],
                ['label', start_label],
                [  # maybe exit loop / break.
                    'if',
                    ['le', ['mload', loop_memory_position], 0],
                    ['goto', exit_label]
                ],
                [  # push onto stack
                    'mload',
                    ['add', begin_pos, ['sub', ['mload', loop_memory_position], 32]]
                ],
                [  # decrement i by 32.
                    'mstore',
                    loop_memory_position,
                    ['sub', ['mload', loop_memory_position], 32],
                ],
                ['goto', start_label],
                ['label', exit_label]
            ]
            return ['seq_unchecked'] + [mloads] + [['jump', ['mload', context.callback_ptr]]]
    else:
        return ['return', begin_pos, _size]


# Generate code for returning a tuple or struct.
def gen_tuple_return(stmt, context, sub):
    # Is from a call expression.
    if sub.args and len(sub.args[0].args) > 0 and sub.args[0].args[0].value == 'call':
        # self-call to public.
        mem_pos = sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        return LLLnode.from_list(['return', mem_pos, mem_size], typ=sub.typ)

    elif (sub.annotation and 'Internal Call' in sub.annotation):
        mem_pos = sub.args[-1].value if sub.value == 'seq_unchecked' else sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        # Add zero padder if bytes are present in output.
        zero_padder = ['pass']
        byte_arrays = [
            (i, x)
            for i, x
            in enumerate(sub.typ.tuple_members())
            if isinstance(x, ByteArrayLike)
        ]
        if byte_arrays:
            i, x = byte_arrays[-1]
            zero_padder = zero_pad(bytez_placeholder=[
                'add',
                mem_pos,
                ['mload', mem_pos + i * 32]
            ], maxlen=x.maxlen, context=context)
        return LLLnode.from_list(['seq'] + [sub] + [zero_padder] + [
            make_return_stmt(stmt, context, mem_pos, mem_size)
        ], typ=sub.typ, pos=getpos(stmt), valency=0)

    subs = []
    # Pre-allocate loop_memory_position if required for private function returning.
    loop_memory_position = (
        context.new_placeholder(typ=BaseType('uint256')) if context.is_private else None
    )
    # Allocate dynamic off set counter, to keep track of the total packed dynamic data size.
    dynamic_offset_counter_placeholder = context.new_placeholder(typ=BaseType('uint256'))
    dynamic_offset_counter = LLLnode(
        dynamic_offset_counter_placeholder,
        typ=None,
        annotation="dynamic_offset_counter"  # dynamic offset position counter.
    )
    new_sub = LLLnode.from_list(
        context.new_placeholder(typ=BaseType('uint256')),
        typ=context.return_type,
        location='memory',
        annotation='new_sub',
    )
    left_token = LLLnode.from_list('_loc', typ=new_sub.typ, location="memory")

    def get_dynamic_offset_value():
        # Get value of dynamic offset counter.
        return ['mload', dynamic_offset_counter]

    def increment_dynamic_offset(dynamic_spot):
        # Increment dyanmic offset counter in memory.
        return [
            'mstore', dynamic_offset_counter,
            ['add',
                ['add', ['ceil32', ['mload', dynamic_spot]], 32],
                ['mload', dynamic_offset_counter]]
        ]

    if not isinstance(context.return_type, TupleLike):
        raise TypeMismatchException(
            'Trying to return %r when expecting %r' % (sub.typ, context.return_type), getpos(stmt)
        )
    items = context.return_type.tuple_items()

    dynamic_offset_start = 32 * len(items)  # The static list of args end.

    for i, (key, typ) in enumerate(items):
        variable_offset = LLLnode.from_list(
            ['add', 32 * i, left_token],
            typ=typ,
            annotation='variable_offset',
        )  # variable offset of destination
        if sub.typ.is_literal:
            arg = sub.args[i]
        else:
            arg = add_variable_offset(parent=sub, key=key, pos=getpos(stmt))

        if isinstance(typ, ByteArrayLike):
            # Store offset pointer value.
            subs.append(['mstore', variable_offset, get_dynamic_offset_value()])

            # Store dynamic data, from offset pointer onwards.
            dynamic_spot = LLLnode.from_list(
                ['add', left_token, get_dynamic_offset_value()],
                location="memory",
                typ=typ,
                annotation='dynamic_spot',
            )
            subs.append(make_setter(dynamic_spot, arg, location="memory", pos=getpos(stmt)))
            subs.append(increment_dynamic_offset(dynamic_spot))

        elif isinstance(typ, BaseType):
            subs.append(make_setter(variable_offset, arg, "memory", pos=getpos(stmt)))
        elif isinstance(typ, TupleLike):
            subs.append(gen_tuple_return(stmt, context, arg))
        else:
            # Maybe this should panic because the type error should be
            # caught at an earlier type-checking stage.
            raise TypeMismatchException("Can't return type %s as part of tuple" % arg.typ, stmt)

    setter = LLLnode.from_list(
        ['seq',
            ['mstore', dynamic_offset_counter, dynamic_offset_start],
            ['with', '_loc', new_sub, ['seq'] + subs]],
        typ=None
    )

    return LLLnode.from_list([
        'seq',
        setter,
        make_return_stmt(stmt, context, new_sub, get_dynamic_offset_value(), loop_memory_position)
    ], typ=None, pos=getpos(stmt), valency=0)
