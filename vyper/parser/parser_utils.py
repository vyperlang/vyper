import ast as python_ast
from decimal import (
    Decimal,
    getcontext,
)
from typing import (
    Any,
    List,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    ArrayIndexException,
    ConstancyViolation,
    InvalidLiteral,
    StructureException,
    TypeMismatch,
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
from vyper.utils import (
    DECIMAL_DIVISOR,
    GAS_IDENTITY,
    GAS_IDENTITYWORD,
    MemoryPositions,
    SizeLimits,
)

getcontext().prec = 78  # MAX_UINT256 < 1e78


# Get a decimal number as a fraction with denominator multiple of 10
def get_number_as_fraction(expr, context):
    context_line = context.origcode.splitlines()[expr.lineno - 1]
    context_slice = context_line[expr.col_offset:expr.end_col_offset]
    literal = Decimal(context_slice)
    sign, digits, exponent = literal.as_tuple()

    if exponent < -10:
        raise InvalidLiteral(
                f"`decimal` literal cannot have more than 10 decimal places: {literal}",
                expr
            )

    sign = (-1 if sign == 1 else 1)  # Positive Decimal has `sign` of 0, negative `sign` of 1
    # Decimal `digits` is a tuple of each digit, so convert to a regular integer
    top = int(Decimal((0, digits, 0)))
    top = sign * top * 10**(exponent if exponent > 0 else 0)  # Convert to a fixed point integer
    bottom = (1 if exponent > 0 else 10**abs(exponent))  # Make denominator a power of 10
    assert Decimal(top) / Decimal(bottom) == literal  # Sanity check

    # TODO: Would be best to raise >10 decimal place exception here
    #       (unless Decimal is used more widely)

    return context_slice, top, bottom


# Copies byte array
def make_byte_array_copier(destination, source, pos=None):
    if not isinstance(source.typ, (ByteArrayLike, NullType)):
        btype = 'byte array' if isinstance(destination.typ, ByteArrayType) else 'string'
        raise TypeMismatch(f"Can only set a {btype} to another {btype}", pos)
    if isinstance(source.typ, ByteArrayLike) and source.typ.maxlen > destination.typ.maxlen:
        raise TypeMismatch(
            f"Cannot cast from greater max-length {source.typ.maxlen} to shorter "
            f"max-length {destination.typ.maxlen}"
        )
    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        gas_calculation = GAS_IDENTITY + GAS_IDENTITYWORD * (ceil32(source.typ.maxlen) // 32)
        o = LLLnode.from_list([
            'with', '_source', source, [
                'with', '_sz', ['add', 32, ['mload', '_source']], [
                    'assert', ['call', ['gas'], 4, 0, '_source', '_sz', destination, '_sz']]]],  # noqa: E501
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
                ['call', ['gas'], 4, 0, source, '_l', destination, '_l']
            ]
        ], typ=None, annotation=f'copy byte slice dest: {str(destination)}')
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
        annotation=f'copy byte slice src: {source} dst: {destination}',
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
    ], typ=BaseType(out_type), annotation=f'bytearray to number ({out_type})')


def get_length(arg):
    if arg.location == "memory":
        return LLLnode.from_list(['mload', arg], typ=BaseType('int128'))
    elif arg.location == "storage":
        return LLLnode.from_list(['sload', ['sha3_32', arg]], typ=BaseType('int128'))


def getpos(node):
    return (
        node.lineno,
        node.col_offset,
        getattr(node, 'end_lineno', None),
        getattr(node, 'end_col_offset', None)
    )


def set_offsets(node, pos):
    # TODO replace this with a visitor pattern
    for field in node.get_slots():
        item = getattr(node, field, None)
        if isinstance(item, vy_ast.VyperNode):
            set_offsets(item, pos)
        elif isinstance(item, list):
            for i in item:
                if isinstance(i, vy_ast.VyperNode):
                    set_offsets(i, pos)
    node.lineno, node.col_offset, node.end_lineno, node.end_col_offset = pos


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
def add_variable_offset(parent, key, pos, array_bounds_check=True):
    typ, location = parent.typ, parent.location
    if isinstance(typ, TupleLike):
        if isinstance(typ, StructType):
            if not isinstance(key, str):
                raise TypeMismatch(
                    f"Expecting a member variable access; cannot access element {key}", pos
                )
            if key not in typ.members:
                raise TypeMismatch(f"Object does not have member variable {key}", pos)
            subtype = typ.members[key]
            attrs = list(typ.tuple_keys())

            if key not in attrs:
                raise TypeMismatch(
                    f"Member {key} not found. Only the following available: " + " ".join(attrs),
                    pos
                )
            index = attrs.index(key)
            annotation = key
        else:
            if not isinstance(key, int):
                raise TypeMismatch(
                    f"Expecting a static index; cannot access element {key}", pos
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
        elif location in ('calldata', 'memory'):
            offset = 0
            for i in range(index):
                offset += 32 * get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(['add', offset, parent],
                                     typ=typ.members[key],
                                     location=location,
                                     annotation=annotation)
        else:
            raise TypeMismatch("Not expecting a member variable access", pos)

    elif isinstance(typ, MappingType):

        if isinstance(key.typ, ByteArrayLike):
            if not isinstance(typ.keytype, ByteArrayLike) or (typ.keytype.maxlen < key.typ.maxlen):
                raise TypeMismatch(
                    "Mapping keys of bytes cannot be cast, use exact same bytes type of: "
                    f"{str(typ.keytype)}",
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
        elif location in ('memory', 'calldata'):
            raise TypeMismatch(
                "Can only have fixed-side arrays in memory, not mappings", pos
            )

    elif isinstance(typ, ListType):

        subtype = typ.subtype
        k = unwrap_location(key)
        if not is_base_type(key.typ, ('int128', 'uint256')):
            raise TypeMismatch(f'Invalid type for array index: {key.typ}', pos)

        if not array_bounds_check:
            sub = k
        elif key.typ.is_literal:  # note: BaseType always has is_literal attr
            # perform the check at compile time and elide the runtime check.
            if key.value < 0 or key.value >= typ.count:
                raise ArrayIndexException(
                        'Array index determined to be out of bounds. '
                        f'Index is {key.value} but array size is {typ.count}',
                        pos)
            sub = k
        else:
            # this works, even for int128. for int128, since two's-complement
            # is used, if the index is negative, (unsigned) LT will interpret
            # it as a very large number, larger than any practical value for
            # an array index, and the clamp will throw an error.
            sub = ['uclamplt', k, typ.count]

        if location == 'storage':
            return LLLnode.from_list(['add', ['sha3_32', parent], sub],
                                     typ=subtype,
                                     location='storage',
                                     pos=pos)
        elif location == 'storage_prehashed':
            return LLLnode.from_list(['add', parent, sub],
                                     typ=subtype,
                                     location='storage',
                                     pos=pos)
        elif location in ('calldata', 'memory'):
            offset = 32 * get_size_of_type(subtype)
            return LLLnode.from_list(
                ['add', ['mul', offset, sub], parent],
                typ=subtype,
                location=location,
                pos=pos
            )
        else:
            raise TypeMismatch("Not expecting an array access ", pos)
    else:
        raise TypeMismatch(f"Cannot access the child of a constant variable! {typ}", pos)


# Convert from one base type to another
def base_type_conversion(orig, frm, to, pos, in_function_call=False):
    orig = unwrap_location(orig)
    is_valid_int128_to_decimal = (
        is_base_type(frm, 'int128') and is_base_type(to, 'decimal')
    ) and are_units_compatible(frm, to)

    if getattr(frm, 'is_literal', False):
        if frm.typ in ('int128', 'uint256'):
            if not SizeLimits.in_bounds(frm.typ, orig.value):
                raise InvalidLiteral(f"Number out of range: {orig.value}", pos)
            # Special Case: Literals in function calls should always convey unit type as well.
            if in_function_call and not (frm.unit == to.unit and frm.positional == to.positional):
                raise InvalidLiteral(
                    f"Function calls require explicit unit definitions on calls, expected {to}",
                    pos
                )
        if to.typ in ('int128', 'uint256'):
            if not SizeLimits.in_bounds(to.typ, orig.value):
                raise InvalidLiteral(f"Number out of range: {orig.value}", pos)

    if not isinstance(frm, (BaseType, NullType)) or not isinstance(to, BaseType):
        raise TypeMismatch(
            f"Base type conversion from or to non-base type: {frm} {to}", pos
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
            raise TypeMismatch(  # pragma: no cover
                f"Cannot convert null-type object to type {to}", pos
            )
        return LLLnode.from_list(0, typ=to)
    # Integer literal conversion.
    elif (frm.typ, to.typ, frm.is_literal) == ('int128', 'uint256', True):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    else:
        raise TypeMismatch(
            f"Typecasting from base type {frm} to {to} unavailable", pos
        )


# Unwrap location
def unwrap_location(orig):
    if orig.location == 'memory':
        return LLLnode.from_list(['mload', orig], typ=orig.typ)
    elif orig.location == 'storage':
        return LLLnode.from_list(['sload', orig], typ=orig.typ)
    elif orig.location == 'calldata':
        return LLLnode.from_list(['calldataload', orig], typ=orig.typ)
    else:
        return orig


# Pack function arguments for a call
def pack_arguments(signature, args, context, stmt_expr, return_placeholder=True):
    pos = getpos(stmt_expr)
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
            f"Wrong number of args for: {signature.name} "
            f"({actual_arg_count} args given, expected {expected_arg_count}",
            stmt_expr
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
                raise TypeMismatch("Cannot pack bytearray in struct", stmt_expr)
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
            raise TypeMismatch(f"Cannot pack argument of type {typ}", stmt_expr)

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
        raise TypeMismatch("Cannot copy mappings; can only copy individual elements", pos)
    # Arrays
    elif isinstance(left.typ, ListType):
        # Cannot do something like [a, b, c] = [1, 2, 3]
        if left.value == "multi":
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, (ListType, NullType)):
            raise TypeMismatch(
                f"Setter type mismatch: left side is array, right side is {right.typ}", pos
            )
        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        # Type checks
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, ListType):
                raise TypeMismatch("Left side is array, right side is not", pos)
            if left.typ.count != right.typ.count:
                raise TypeMismatch("Mismatched number of elements", pos)
        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != left.typ.count:
                raise TypeMismatch("Mismatched number of elements", pos)
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(
                    left_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                    array_bounds_check=False,
                ), right.args[i], location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        # CC 20190619 probably not needed as of #1106
        elif isinstance(right.typ, NullType):
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(
                    left_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                    array_bounds_check=False,
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
                    array_bounds_check=False,
                ), add_variable_offset(
                    right_token,
                    LLLnode.from_list(i, typ='int128'),
                    pos=pos,
                    array_bounds_check=False,
                ), location, pos=pos))
            return LLLnode.from_list([
                'with', '_L', left, [
                    'with', '_R', right, ['seq'] + subs]
            ], typ=None)
    # Structs
    elif isinstance(left.typ, TupleLike):
        if left.value == "multi" and isinstance(left.typ, StructType):
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, left.typ.__class__):
                raise TypeMismatch(
                    f"Setter type mismatch: left side is {left.typ}, right side is {right.typ}",
                    pos,
                )
            if isinstance(left.typ, StructType):
                for k in right.args:
                    if k.value is None:
                        raise InvalidLiteral(
                            'Setting struct value to None is not allowed, use a default value.',
                            pos,
                        )
                for k in left.typ.members:
                    if k not in right.typ.members:
                        raise TypeMismatch(
                            f"Keys don't match for structs, missing {k}",
                            pos,
                        )
                for k in right.typ.members:
                    if k not in left.typ.members:
                        raise TypeMismatch(
                            f"Keys don't match for structs, extra {k}",
                            pos,
                        )
                if left.typ.name != right.typ.name:
                    raise TypeMismatch(f"Expected {left.typ}, got {right.typ}", pos)
            else:
                if len(left.typ.members) != len(right.typ.members):
                    raise TypeMismatch(
                        "Tuple lengths don't match, "
                        f"{len(left.typ.members)} vs {len(right.typ.members)}",
                        pos,
                    )

        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        keyz = left.typ.tuple_keys()

        # If the left side is a literal
        if left.value == 'multi':
            locations = [arg.location for arg in left.args]
        else:
            locations = [location for _ in keyz]

        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != len(keyz):
                raise TypeMismatch("Mismatched number of elements", pos)
            # get the RHS arguments into a dict because
            # they are not guaranteed to be in the same order
            # the LHS keys.
            right_args = dict(zip(right.typ.tuple_keys(), right.args))
            subs = []
            for (key, loc) in zip(keyz, locations):
                subs.append(make_setter(
                    add_variable_offset(left_token, key, pos=pos),
                    right_args[key],
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
            for var_arg in left.args:
                if var_arg.location == 'calldata':
                    raise ConstancyViolation(
                        f"Cannot modify function argument: {var_arg.annotation}", pos
                    )
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


# zero pad a bytearray according to the ABI spec. The last word
# of the byte array needs to be right-padded with zeroes.
def zero_pad(bytez_placeholder):
    # calldatacopy from past-the-end gives zero bytes.
    # cf. YP H.2 (ops section) with CALLDATACOPY spec.
    len_ = ['mload', bytez_placeholder]
    dst = ['add', ['add', bytez_placeholder, 32], 'len']
    # the runtime length of the data rounded up to nearest 32
    # from spec:
    #   the actual value of X as a byte sequence,
    #   followed by the *minimum* number of zero-bytes
    #   such that len(enc(X)) is a multiple of 32.
    num_zero_bytes = ['sub', ['ceil32', 'len'], 'len']
    return LLLnode.from_list(
            ['with', 'len', len_,
                ['with', 'dst', dst,
                    # calldatacopy mempos calldatapos len
                    ['calldatacopy', 'dst', 'calldatasize', num_zero_bytes]]],
            annotation="Zero pad",
            )
