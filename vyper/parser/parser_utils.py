import ast

from vyper.utils import GAS_IDENTITY, GAS_IDENTITYWORD

from vyper.exceptions import (
    InvalidLiteralException,
    TypeMismatchException
)
from vyper.parser.lll_node import (
    LLLnode
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    ContractType,
    NullType,
    StructType,
    MappingType,
    TupleType,
    ListType,
)
from vyper.types import (
    is_base_type,
    are_units_compatible,
    get_size_of_type,
    ceil32
)
from vyper.utils import (
    SizeLimits,
    MemoryPositions,
    DECIMAL_DIVISOR
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
def make_byte_array_copier(destination, source):
    if not isinstance(source.typ, (ByteArrayType, NullType)):
        raise TypeMismatchException("Can only set a byte array to another byte array")
    if isinstance(source.typ, ByteArrayType) and source.typ.maxlen > destination.typ.maxlen:
        raise TypeMismatchException("Cannot cast from greater max-length %d to shorter max-length %d" % (source.typ.maxlen, destination.typ.maxlen))
    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        gas_calculation = GAS_IDENTITY + GAS_IDENTITYWORD * (ceil32(source.typ.maxlen) // 32)
        o = LLLnode.from_list(
            ['with', '_source', source,
                ['with', '_sz', ['add', 32, ['mload', '_source']],
                    ['assert', ['call', ['add', 18, ['div', '_sz', 10]], 4, 0, '_source', '_sz', destination, '_sz']]]],
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
        pos_node = LLLnode.from_list(['sha3_32', pos_node], typ=source.typ, location=source.location)
    else:
        raise Exception("Unsupported location:" + source.location)
    if destination.location == "storage":
        destination = LLLnode.from_list(['sha3_32', destination], typ=destination.typ, location=destination.location)
    # Maximum theoretical length
    max_length = 32 if isinstance(source.typ, NullType) else source.typ.maxlen + 32
    return LLLnode.from_list(['with', '_pos', 0 if isinstance(source.typ, NullType) else source,
                                make_byte_slice_copier(destination, pos_node, length, max_length)], typ=None)


# Copy bytes
# Accepts 4 arguments:
# (i) an LLL node for the start position of the source
# (ii) an LLL node for the start position of the destination
# (iii) an LLL node for the length
# (iv) a constant for the max length
def make_byte_slice_copier(destination, source, length, max_length):
    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        return LLLnode.from_list(['with', '_l', max_length,
                                    ['pop', ['call', 18 + max_length // 10, 4, 0, source,
                                             '_l', destination, '_l']]], typ=None, annotation='copy byte slice dest: %s' % str(destination))
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
        setter = ['mstore', ['add', '_opos', ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]], loader]
    elif destination.location == "storage":
        setter = ['sstore', ['add', '_opos', ['mload', MemoryPositions.FREE_LOOP_INDEX]], loader]
    else:
        raise Exception("Unsupported location:" + destination.location)
    # Check to see if we hit the length
    checker = ['if', ['gt', ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]], '_actual_len'], 'break']
    # Make a loop to do the copying
    o = ['with', '_pos', source,
            ['with', '_opos', destination,
                ['with', '_actual_len', length,
                    ['repeat', MemoryPositions.FREE_LOOP_INDEX, 0, (max_length + 31) // 32,
                        ['seq', checker, setter]]]]]
    return LLLnode.from_list(o, typ=None, annotation='copy byte slice src: %s dst: %s' % (source, destination))


# Takes a <32 byte array as input, and outputs a number.
def byte_array_to_num(arg, expr, out_type, offset=32,):
    if arg.location == "memory":
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('int128'))
        first_el_getter = LLLnode.from_list(['mload', ['add', 32, '_sub']], typ=BaseType('int128'))
    elif arg.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('int128'))
        first_el_getter = LLLnode.from_list(['sload', ['add', 1, ['sha3_32', '_sub']]], typ=BaseType('int128'))
    if out_type == 'int128':
        result = ['clamp',
                     ['mload', MemoryPositions.MINNUM],
                     ['div', '_el1', ['exp', 256, ['sub', 32, '_len']]],
                     ['mload', MemoryPositions.MAXNUM]]
    elif out_type == 'uint256':
        result = ['div', '_el1', ['exp', 256, ['sub', offset, '_len']]]
    return LLLnode.from_list(['with', '_sub', arg,
                                 ['with', '_el1', first_el_getter,
                                    ['with', '_len', ['clamp', 0, lengetter, 32],
                                       result
                                       ]]],
                             typ=BaseType(out_type), annotation='bytearray to number (%s)' % out_type)


def get_length(arg):
    if arg.location == "memory":
        return LLLnode.from_list(['mload', arg], typ=BaseType('int128'))
    elif arg.location == "storage":
        return LLLnode.from_list(['sload', ['sha3_32', arg]], typ=BaseType('int128'))


def getpos(node):
    return (node.lineno, node.col_offset)


# Take a value representing a memory or storage location, and descend down to an element or member variable
def add_variable_offset(parent, key, pos):
    typ, location = parent.typ, parent.location
    if isinstance(typ, (StructType, TupleType)):
        if isinstance(typ, StructType):
            if not isinstance(key, str):
                raise TypeMismatchException("Expecting a member variable access; cannot access element %r" % key, pos)
            if key not in typ.members:
                raise TypeMismatchException("Object does not have member variable %s" % key, pos)
            subtype = typ.members[key]
            attrs = sorted(typ.members.keys())

            if key not in attrs:
                raise TypeMismatchException("Member %s not found. Only the following available: %s" % (key, " ".join(attrs)), pos)
            index = attrs.index(key)
            annotation = key
        else:
            if not isinstance(key, int):
                raise TypeMismatchException("Expecting a static index; cannot access element %r" % key, pos)
            attrs = list(range(len(typ.members)))
            index = key
            annotation = None
        if location == 'storage':
            return LLLnode.from_list(['add', ['sha3_32', parent], LLLnode.from_list(index, annotation=annotation)],
                                     typ=subtype,
                                     location='storage')
        elif location == 'storage_prehashed':
            return LLLnode.from_list(['add', parent, LLLnode.from_list(index, annotation=annotation)],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            offset = 0
            for i in range(index):
                offset += 32 * get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(['add', offset, parent],
                                     typ=typ.members[key],
                                     location='memory',
                                     annotation=annotation)
        else:
            raise TypeMismatchException("Not expecting a member variable access")

    elif isinstance(typ, MappingType):

        if isinstance(key.typ, ByteArrayType):
            if not isinstance(typ.keytype, ByteArrayType) or (typ.keytype.maxlen < key.typ.maxlen):
                raise TypeMismatchException(
                    'Mapping keys of bytes cannot be cast, use exact same bytes type of: %s' % str(typ.keytype), pos
                )
            subtype = typ.valuetype
            if len(key.args[0].args) >= 3:  # handle bytes literal.
                sub = LLLnode.from_list([
                    'seq',
                    key,
                    ['sha3', ['add', key.args[0].args[-1], 32], ['mload', key.args[0].args[-1]]]
                ])
            else:
                sub = LLLnode.from_list(['sha3', ['add', key.args[0].value, 32], ['mload', key.args[0].value]])
        else:
            subtype = typ.valuetype
            sub = base_type_conversion(key, key.typ, typ.keytype, pos=pos)

        if location == 'storage':
            return LLLnode.from_list(['sha3_64', parent, sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            raise TypeMismatchException("Can only have fixed-side arrays in memory, not mappings", pos)

    elif isinstance(typ, ListType):

        subtype = typ.subtype
        sub = ['uclamplt', base_type_conversion(key, key.typ, BaseType('int128'), pos=pos), typ.count]

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
            return LLLnode.from_list(['add', ['mul', offset, sub], parent],
                                      typ=subtype,
                                      location='memory')
        else:
            raise TypeMismatchException("Not expecting an array access ", pos)
    else:
        raise TypeMismatchException("Cannot access the child of a constant variable! %r" % typ, pos)


# Convert from one base type to another
def base_type_conversion(orig, frm, to, pos):
    orig = unwrap_location(orig)
    if getattr(frm, 'is_literal', False) and frm.typ in ('int128', 'uint256') and not SizeLimits.in_bounds(frm.typ, orig.value):
        raise InvalidLiteralException("Number out of range: " + str(orig.value), pos)
    if not isinstance(frm, (BaseType, NullType)) or not isinstance(to, BaseType):
        raise TypeMismatchException("Base type conversion from or to non-base type: %r %r" % (frm, to), pos)
    elif is_base_type(frm, to.typ) and are_units_compatible(frm, to):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    elif is_base_type(frm, 'int128') and is_base_type(to, 'decimal') and are_units_compatible(frm, to):
        return LLLnode.from_list(['mul', orig, DECIMAL_DIVISOR], typ=BaseType('decimal', to.unit, to.positional))
    elif isinstance(frm, NullType):
        if to.typ not in ('int128', 'bool', 'uint256', 'address', 'bytes32', 'decimal'):
            # This is only to future proof the use of  base_type_conversion.
            raise TypeMismatchException("Cannot convert null-type object to type %r" % to, pos)  # pragma: no cover
        return LLLnode.from_list(0, typ=to)
    elif isinstance(to, ContractType) and frm.typ == 'address':
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    # Integer literal conversion.
    elif (frm.typ, to.typ, frm.is_literal) == ('int128', 'uint256', True):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    else:
        raise TypeMismatchException("Typecasting from base type %r to %r unavailable" % (frm, to), pos)


# Unwrap location
def unwrap_location(orig):
    if orig.location == 'memory':
        return LLLnode.from_list(['mload', orig], typ=orig.typ)
    elif orig.location == 'storage':
        return LLLnode.from_list(['sload', orig], typ=orig.typ)
    else:
        return orig


# Decorate every node of an AST tree with the original source code.
# This is necessary to facilitate error pretty-printing.
def decorate_ast_with_source(_ast, code):

    class MyVisitor(ast.NodeVisitor):
        def visit(self, node):
            self.generic_visit(node)
            node.source_code = code

    MyVisitor().visit(_ast)


def resolve_negative_literals(_ast):

    class RewriteUnaryOp(ast.NodeTransformer):
        def visit_UnaryOp(self, node):
            if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Num):
                node.operand.n = 0 - node.operand.n
                return node.operand
            else:
                return node

    return RewriteUnaryOp().visit(_ast)
