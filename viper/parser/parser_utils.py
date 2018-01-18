import re

from ethereum import opcodes

from viper.exceptions import TypeMismatchException
from viper.opcodes import comb_opcodes
from viper.types import (
    BaseType,
    ByteArrayType,
    NodeType,
    NullType,
    StructType,
    MappingType,
    TupleType,
    ListType,
)
from viper.types import (
    is_base_type,
    are_units_compatible,
    get_size_of_type,
    ceil32
)
from viper.utils import MemoryPositions, DECIMAL_DIVISOR


class NullAttractor():
    def __add__(self, other):
        return NullAttractor()

    def __repr__(self):
        return 'None'

    __radd__ = __add__
    __mul__ = __add__


# Data structure for LLL parse tree
class LLLnode():
    repr_show_gas = False

    def __init__(self, value, args=None, typ=None, location=None, pos=None, annotation='', mutable=True, add_gas_estimate=0):
        if args is None:
            args = []

        self.value = value
        self.args = args
        self.typ = typ
        assert isinstance(self.typ, NodeType) or self.typ is None, repr(self.typ)
        self.location = location
        self.pos = pos
        self.annotation = annotation
        self.mutable = mutable
        self.add_gas_estimate = add_gas_estimate
        # Determine this node's valency (1 if it pushes a value on the stack,
        # 0 otherwise) and checks to make sure the number and valencies of
        # children are correct. Also, find an upper bound on gas consumption
        # Numbers
        if isinstance(self.value, int):
            self.valency = 1
            self.gas = 5
        elif isinstance(self.value, str):
            # Opcodes and pseudo-opcodes (eg. clamp)
            if self.value.upper() in comb_opcodes:
                _, ins, outs, gas = comb_opcodes[self.value.upper()]
                self.valency = outs
                if len(self.args) != ins:
                    raise Exception("Number of arguments mismatched: %r %r" % (self.value, self.args))
                # We add 2 per stack height at push time and take it back
                # at pop time; this makes `break` easier to handle
                self.gas = gas + 2 * (outs - ins)
                for arg in self.args:
                    if arg.valency == 0:
                        raise Exception("Can't have a zerovalent argument to an opcode or a pseudo-opcode! %r" % arg)
                    self.gas += arg.gas
                # Dynamic gas cost: 8 gas for each byte of logging data
                if self.value.upper()[0:3] == 'LOG' and isinstance(self.args[1].value, int):
                    self.gas += self.args[1].value * 8
                # Dynamic gas cost: non-zero-valued call
                if self.value.upper() == 'CALL' and self.args[2].value != 0:
                    self.gas += 34000
                # Dynamic gas cost: filling sstore (ie. not clearing)
                elif self.value.upper() == 'SSTORE' and self.args[1].value != 0:
                    self.gas += 15000
                # Dynamic gas cost: calldatacopy
                elif self.value.upper() in ('CALLDATACOPY', 'CODECOPY'):
                    size = 34000
                    if isinstance(self.args[2].value, int):
                        size = self.args[2].value
                    elif isinstance(self.args[2], LLLnode) and len(self.args[2].args) > 0:
                        size = self.args[2].args / [-1].value
                    self.gas += ceil32(size) // 32 * 3
                # Gas limits in call
                if self.value.upper() == 'CALL' and isinstance(self.args[0].value, int):
                    self.gas += self.args[0].value
            # If statements
            elif self.value == 'if':
                if len(self.args) == 3:
                    self.gas = self.args[0].gas + max(self.args[1].gas, self.args[2].gas) + 3
                    if self.args[1].valency != self.args[2].valency:
                        raise Exception("Valency mismatch between then and else clause: %r %r" % (self.args[1], self.args[2]))
                if len(self.args) == 2:
                    self.gas = self.args[0].gas + self.args[1].gas + 17
                    if self.args[1].valency:
                        raise Exception("2-clause if statement must have a zerovalent body: %r" % self.args[1])
                if not self.args[0].valency:
                    raise Exception("Can't have a zerovalent argument as a test to an if statement! %r" % self.args[0])
                if len(self.args) not in (2, 3):
                    raise Exception("If can only have 2 or 3 arguments")
                self.valency = self.args[1].valency
            # With statements: with <var> <initial> <statement>
            elif self.value == 'with':
                if len(self.args) != 3:
                    raise Exception("With statement must have 3 arguments")
                if len(self.args[0].args) or not isinstance(self.args[0].value, str):
                    raise Exception("First argument to with statement must be a variable")
                if not self.args[1].valency:
                    raise Exception("Second argument to with statement (initial value) cannot be zerovalent: %r" % self.args[1])
                self.valency = self.args[2].valency
                self.gas = sum([arg.gas for arg in self.args]) + 5
            # Repeat statements: repeat <index_memloc> <startval> <rounds> <body>
            elif self.value == 'repeat':
                if len(self.args[2].args) or not isinstance(self.args[2].value, int) or self.args[2].value <= 0:
                    raise Exception("Number of times repeated must be a constant nonzero positive integer: %r" % self.args[2])
                if not self.args[0].valency:
                    raise Exception("First argument to repeat (memory location) cannot be zerovalent: %r" % self.args[0])
                if not self.args[1].valency:
                    raise Exception("Second argument to repeat (start value) cannot be zerovalent: %r" % self.args[1])
                if self.args[3].valency:
                    raise Exception("Third argument to repeat (clause to be repeated) must be zerovalent: %r" % self.args[3])
                self.valency = 0
                if self.args[1].value == 'mload' or self.args[1].value == 'sload':
                    rounds = self.args[2].value
                else:
                    rounds = abs(self.args[2].value - self.args[1].value)
                self.gas = rounds * (self.args[3].gas + 50) + 30
            # Seq statements: seq <statement> <statement> ...
            elif self.value == 'seq':
                self.valency = self.args[-1].valency if self.args else 0
                self.gas = sum([arg.gas for arg in self.args]) + 30
            # Multi statements: multi <expr> <expr> ...
            elif self.value == 'multi':
                for arg in self.args:
                    if not arg.valency:
                        raise Exception("Multi expects all children to not be zerovalent: %r" % arg)
                self.valency = sum([arg.valency for arg in self.args])
                self.gas = sum([arg.gas for arg in self.args])
            # LLL brackets (don't bother gas counting)
            elif self.value == 'lll':
                self.valency = 1
                self.gas = NullAttractor()
            # Stack variables
            else:
                self.valency = 1
                self.gas = 5
        elif self.value is None and isinstance(self.typ, NullType):
            self.valency = 1
            self.gas = 5
        else:
            raise Exception("Invalid value for LLL AST node: %r" % self.value)
        assert isinstance(self.args, list)

        self.gas += self.add_gas_estimate

    def to_list(self):
        return [self.value] + [a.to_list() for a in self.args]

    def repr(self):
        if not len(self.args):
            if self.annotation:
                return '%r <%s>' % (self.value, self.annotation)
            else:
                return str(self.value)
        # x = repr(self.to_list())
        # if len(x) < 80:
        #     return x
        o = ''
        if self.annotation:
            o += '/* %s */ \n' % self.annotation
        if self.repr_show_gas and self.gas:
            OKBLUE = '\033[94m'
            ENDC = '\033[0m'
            o += OKBLUE + "{" + ENDC + str(self.gas) + OKBLUE + "} " + ENDC  # add gas for info.
        o += '[' + str(self.value)
        prev_lineno = self.pos[0] if self.pos else None
        arg_lineno = None
        annotated = False
        has_inner_newlines = False
        for arg in self.args:
            o += ',\n  '
            arg_lineno = arg.pos[0] if arg.pos else None
            if arg_lineno is not None and arg_lineno != prev_lineno and self.value in ('seq', 'if'):
                o += '# Line %d\n  ' % (arg_lineno)
                prev_lineno = arg_lineno
                annotated = True
            arg_repr = arg.repr()
            if '\n' in arg_repr:
                has_inner_newlines = True
            sub = arg_repr.replace('\n', '\n  ').strip(' ')
            o += sub
        output = o.rstrip(' ') + ']'
        output_on_one_line = re.sub(r',\n *', ', ', output).replace('\n', '')
        if (len(output_on_one_line) < 80 or len(self.args) == 1) and not annotated and not has_inner_newlines:
            return output_on_one_line
        else:
            return output

    def __repr__(self):
        return self.repr()

    @classmethod
    def from_list(cls, obj, typ=None, location=None, pos=None, annotation=None, mutable=True, add_gas_estimate=0):
        if isinstance(typ, str):
            typ = BaseType(typ)
        if isinstance(obj, LLLnode):
            if obj.pos is None:
                obj.pos = pos
            if obj.location is None:
                obj.location = location
            return obj
        elif not isinstance(obj, list):
            return cls(obj, [], typ, location, pos, annotation, mutable, add_gas_estimate=add_gas_estimate)
        else:
            return cls(obj[0], [cls.from_list(o, pos=pos) for o in obj[1:]], typ, location, pos, annotation, mutable, add_gas_estimate=add_gas_estimate)


# Get a decimal number as a fraction with denominator multiple of 10
def get_number_as_fraction(expr, context):
    context_slice = context.origcode.splitlines()[expr.lineno - 1][expr.col_offset:]
    t = 0
    while t < len(context_slice) and context_slice[t] in '0123456789.':
        t += 1
    top = int(context_slice[:t].replace('.', ''))
    bottom = 1 if '.' not in context_slice[:t] else 10**(t - context_slice[:t].index('.') - 1)
    return context_slice[:t], top, bottom


# Is a number of decimal form (eg. 65281) or 0x form (eg. 0xff01)
def get_original_if_0x_prefixed(expr, context):
    context_slice = context.origcode.splitlines()[expr.lineno - 1][expr.col_offset:]
    if context_slice[:2] != '0x':
        return None
    t = 0
    while t + 2 < len(context_slice) and context_slice[t + 2] in '0123456789abcdefABCDEF':
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
        gas_calculation = opcodes.GIDENTITYBASE + \
            opcodes.GIDENTITYWORD * (ceil32(source.typ.maxlen) // 32)
        o = LLLnode.from_list(
            ['with', '_source', source,
                ['with', '_sz', ['add', 32, ['mload', '_source']],
                    ['assert', ['call', ['add', 18, ['div', '_sz', 10]], 4, 0, '_source', '_sz', destination, '_sz']]]], typ=None, add_gas_estimate=gas_calculation)
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
                                             '_l', destination, '_l']]], typ=None, annotation='copy byte slice')
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
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('num'))
        first_el_getter = LLLnode.from_list(['mload', ['add', 32, '_sub']], typ=BaseType('num'))
    elif arg.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('num'))
        first_el_getter = LLLnode.from_list(['sload', ['add', 1, ['sha3_32', '_sub']]], typ=BaseType('num'))
    if out_type == 'num':
        result = ['clamp',
                     ['mload', MemoryPositions.MINNUM],
                     ['div', '_el1', ['exp', 256, ['sub', 32, '_len']]],
                     ['mload', MemoryPositions.MAXNUM]]
    elif out_type == 'num256':
        result = ['div', '_el1', ['exp', 256, ['sub', offset, '_len']]]
    return LLLnode.from_list(['with', '_sub', arg,
                                 ['with', '_el1', first_el_getter,
                                    ['with', '_len', ['clamp', 0, lengetter, 32],
                                       ['seq',
                                          ['assert', ['or', ['iszero', '_len'], ['div', '_el1', ['exp', 256, 31]]]],
                                          result]]]],
                             typ=BaseType(out_type), annotation='bytearray to number, verify no leading zbytes')


def get_length(arg):
    if arg.location == "memory":
        return LLLnode.from_list(['mload', arg], typ=BaseType('num'))
    elif arg.location == "storage":
        return LLLnode.from_list(['sload', ['sha3_32', arg]], typ=BaseType('num'))


def getpos(node):
    return (node.lineno, node.col_offset)


# Take a value representing a memory or storage location, and descend down to an element or member variable
def add_variable_offset(parent, key):
    typ, location = parent.typ, parent.location
    if isinstance(typ, (StructType, TupleType)):
        if isinstance(typ, StructType):
            if not isinstance(key, str):
                raise TypeMismatchException("Expecting a member variable access; cannot access element %r" % key)
            if key not in typ.members:
                raise TypeMismatchException("Object does not have member variable %s" % key)
            subtype = typ.members[key]
            attrs = sorted(typ.members.keys())

            if key not in attrs:
                raise TypeMismatchException("Member %s not found. Only the following available: %s" % (key, " ".join(attrs)))
            index = attrs.index(key)
            annotation = key
        else:
            if not isinstance(key, int):
                raise TypeMismatchException("Expecting a static index; cannot access element %r" % key)
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
    elif isinstance(typ, (ListType, MappingType)):
        if isinstance(typ, ListType):
            subtype = typ.subtype
            sub = ['uclamplt', base_type_conversion(key, key.typ, BaseType('num')), typ.count]
        elif isinstance(typ, MappingType) and isinstance(key.typ, ByteArrayType):
            if not isinstance(typ.keytype, ByteArrayType) or (typ.keytype.maxlen < key.typ.maxlen):
                raise TypeMismatchException('Mapping keys of bytes cannot be cast, use exact same bytes type of: %s', str(typ.keytype))
            subtype = typ.valuetype
            if len(key.args[0].args) == 3:  # handle bytes literal.
                sub = LLLnode.from_list([
                    'seq',
                    key,
                    ['sha3', ['add', key.args[0].args[-1], 32], ceil32(key.typ.maxlen)]
                ])
            else:
                sub = LLLnode.from_list(['sha3', ['add', key.args[0].value, 32], ceil32(key.typ.maxlen)])
        else:
            subtype = typ.valuetype
            sub = base_type_conversion(key, key.typ, typ.keytype)
        if location == 'storage':
            return LLLnode.from_list(['add', ['sha3_32', parent], sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'storage_prehashed':
            return LLLnode.from_list(['add', parent, sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            if isinstance(typ, MappingType):
                raise TypeMismatchException("Can only have fixed-side arrays in memory, not mappings")
            offset = 32 * get_size_of_type(subtype)
            return LLLnode.from_list(['add', ['mul', offset, sub], parent],
                                      typ=subtype,
                                      location='memory')
        else:
            raise TypeMismatchException("Not expecting an array access ")
    else:
        raise TypeMismatchException("Cannot access the child of a constant variable! %r" % typ)


# Convert from one base type to another
def base_type_conversion(orig, frm, to, pos=None):
    orig = unwrap_location(orig)
    if not isinstance(frm, (BaseType, NullType)) or not isinstance(to, BaseType):
        raise TypeMismatchException("Base type conversion from or to non-base type: %r %r" % (frm, to), pos)
    elif is_base_type(frm, to.typ) and are_units_compatible(frm, to):
        return LLLnode(orig.value, orig.args, typ=to, add_gas_estimate=orig.add_gas_estimate)
    elif is_base_type(frm, 'num') and is_base_type(to, 'decimal') and are_units_compatible(frm, to):
        return LLLnode.from_list(['mul', orig, DECIMAL_DIVISOR], typ=BaseType('decimal', to.unit, to.positional))
    elif is_base_type(frm, 'num256') and is_base_type(to, 'num') and are_units_compatible(frm, to):
        return LLLnode.from_list(['uclample', orig, ['mload', MemoryPositions.MAXNUM]], typ=BaseType("num"))
    elif isinstance(frm, NullType):
        if to.typ not in ('num', 'bool', 'num256', 'address', 'bytes32', 'decimal'):
            raise TypeMismatchException("Cannot convert null-type object to type %r" % to, pos)
        return LLLnode.from_list(0, typ=to)
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
