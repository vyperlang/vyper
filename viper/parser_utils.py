from .types import NodeType, BaseType, ListType, MappingType, StructType, \
    MixedType, NullType, ByteArrayType
from .types import base_types, parse_type, canonicalize_type, is_base_type, \
    is_numeric_type, get_size_of_type, is_varname_valid
from .types import combine_units, are_units_compatible, set_default_units
from .exceptions import InvalidTypeException, TypeMismatchException, \
    VariableDeclarationException, StructureException, ConstancyViolationException, \
    InvalidTypeException, InvalidLiteralException
from .opcodes import opcodes, pseudo_opcodes
from .utils import fourbytes_to_int, hex_to_int, bytes_to_int, \
    DECIMAL_DIVISOR, RESERVED_MEMORY, ADDRSIZE_POS, MAXNUM_POS, MINNUM_POS, \
    MAXDECIMAL_POS, MINDECIMAL_POS, FREE_VAR_SPACE, BLANK_SPACE, FREE_LOOP_INDEX

# Data structure for LLL parse tree
class LLLnode():
    def __init__(self, value, args=[], typ=None, location=None):
        self.value = value
        self.args = args
        self.typ = typ
        assert isinstance(self.typ, NodeType) or self.typ is None, repr(self.typ)
        self.location = location
        # Determine this node's valency (1 if it pushes a value on the stack,
        # 0 otherwise) and checks to make sure the number and valencies of
        # children are correct
        # Numbers
        if isinstance(self.value, int):
            self.valency = 1
        elif isinstance(self.value, str):
            # Opcodes and pseudo-opcodes (eg. clamp)
            if self.value.upper() in opcodes or self.value.upper() in pseudo_opcodes:
                record = opcodes.get(self.value.upper(), pseudo_opcodes.get(self.value.upper(), None))
                self.valency = record[2]
                if len(self.args) != record[1]:
                    raise Exception("Number of arguments mismatched: %r %r" % (self.value, self.args))
                for arg in self.args:
                    if arg.valency == 0:
                        raise Exception("Can't have a zerovalent argument to an opcode or a pseudo-opcode! %r" % arg)
            # If statements
            elif self.value == 'if':
                if len(self.args) == 3:
                    if self.args[1].valency != self.args[2].valency:
                        raise Exception("Valency mismatch between then and else clause: %r %r" % (self.args[1], self.args[2]))
                if len(self.args) == 2 and self.args[1].valency:
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
            # Seq statements: seq <statement> <statement> ...
            elif self.value == 'seq':
                self.valency = self.args[-1].valency if self.args else 0
            # Multi statements: multi <expr> <expr> ...
            elif self.value == 'multi':
                for arg in self.args:
                    if not arg.valency:
                        raise Exception("Multi expects all children to not be zerovalent: %r" % arg)
                self.valency = sum([arg.valency for arg in self.args])
            # Variables
            else:
                self.valency = 1
        elif self.value is None and isinstance(self.typ, NullType):
            self.valency = 1
        else:
            raise Exception("Invalid value for LLL AST node: %r" % self.value)
        assert isinstance(self.args, list)

    def to_list(self):
        return [self.value] + [a.to_list() for a in self.args]

    def repr(self):
        x = repr(self.to_list())
        if len(x) < 80:
            return x
        o = '[' + repr(self.value) + ',\n  '
        for arg in self.args:
            sub = arg.repr().replace('\n', '\n  ').strip(' ')
            o += sub + '\n  '
        return o.rstrip(' ') + ']'

    def __repr__(self):
        return self.repr()

    @classmethod
    def from_list(cls, obj, typ=None, location=None):
        if isinstance(typ, str):
            typ = BaseType(typ)
        if isinstance(obj, LLLnode):
            return obj
        elif not isinstance(obj, list):
            return cls(obj, [], typ, location)
        else:
            return cls(obj[0], [cls.from_list(o) for o in obj[1:]], typ, location)

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
    return context_slice[:t+2]

# Copies byte array
def make_byte_array_copier(destination, source):
    if not isinstance(source.typ, (ByteArrayType, NullType)):
        raise TypeMismatchException("Can only set a byte array to another byte array")
    if isinstance(source.typ, ByteArrayType) and source.typ.maxlen > destination.typ.maxlen:
        raise TypeMismatchException("Cannot cast from greater max-length %d to shorter max-length %d" % (source.typ.maxlen, destination.typ.maxlen))
    # Special case: calldata to memory
    if source.location == "calldata" and destination.location == "memory":
        return LLLnode.from_list(['calldatacopy', destination, ['add', 4, source], ['add', 32, ['calldataload', ['add', 4, source]]]], typ=None)
    pos_node = LLLnode.from_list('_pos', typ=source.typ, location=source.location)
    # Get the length
    if isinstance(source.typ, NullType):
        length = 1
    elif source.location == "calldata":
        length = ['add', ['calldataload', ['add', 4, '_pos']], 32]
    elif source.location == "memory":
        length = ['add', ['mload', '_pos'], 32]
    elif source.location == "storage":
        length = ['add', ['sload', '_pos'], 32]
        pos_node = LLLnode.from_list(['sha3_32', pos_node], typ=source.typ, location=source.location)
    else:
        raise Exception("Unsupported location:"+source.location)
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
    # Special case: calldata to memory
    if source.location == "calldata" and destination.location == "memory":
        return LLLnode.from_list(['calldatacopy', destination, ['add', 4, source], max_length], typ=None)
    # Special case: memory to memory
    elif source.location == "memory" and destination.location == "memory":
        return LLLnode.from_list(['with', '_l', max_length,
                                    ['pop', ['call', 18 + max_length // 10, 4, 0, source,
                                             '_l', destination, '_l']]], typ=None)
    # Copy over data
    if isinstance(source.typ, NullType):
        loader = 0
    elif source.location == "calldata":
        loader = ['calldataload', ['add', 4, ['add', '_pos', ['mul', 32, ['mload', FREE_LOOP_INDEX]]]]]
    elif source.location == "memory":
        loader = ['mload', ['add', '_pos', ['mul', 32, ['mload', FREE_LOOP_INDEX]]]]
    elif source.location == "storage":
        loader = ['sload', ['add', '_pos', ['mload', FREE_LOOP_INDEX]]]
    else:
        raise Exception("Unsupported location:"+source.location)
    # Where to paste it?
    if destination.location == "calldata":
        raise TypeMismatchException("Cannot set a value in call data")
    elif destination.location == "memory":
        setter = ['mstore', ['add', '_opos', ['mul', 32, ['mload', FREE_LOOP_INDEX]]], loader]
    elif destination.location == "storage":
        setter = ['sstore', ['add', '_opos', ['mload', FREE_LOOP_INDEX]], loader]
    else:
        raise Exception("Unsupported location:"+destination.location)
    # Check to see if we hit the length
    checker = ['if', ['gt', ['mul', 32, ['mload', FREE_LOOP_INDEX]], '_actual_len'], 'break']
    # Make a loop to do the copying
    o = ['with', '_pos', source,
            ['with', '_opos', destination,
                ['with', '_actual_len', length,
                    ['repeat', FREE_LOOP_INDEX, 0, (max_length + 31) // 32,
                        ['seq', checker, setter]]]]]
    return LLLnode.from_list(o, typ=None)

# Takes a <32 byte array as input, and outputs a number.
def byte_array_to_num(arg, expr, out_type):
    if arg.location == "calldata":
        lengetter = LLLnode.from_list(['calldataload', ['add', 4, '_sub']], typ=BaseType('num'))
        first_el_getter = LLLnode.from_list(['calldataload', ['add', 36, '_sub']], typ=BaseType('num'))
    elif arg.location == "memory":
        lengetter = LLLnode.from_list(['mload', '_sub'], typ=BaseType('num'))
        first_el_getter = LLLnode.from_list(['mload', ['add', 32, '_sub']], typ=BaseType('num'))
    elif arg.location == "storage":
        lengetter = LLLnode.from_list(['sload', ['sha3_32', '_sub']], typ=BaseType('num'))
        first_el_getter = LLLnode.from_list(['sload', ['add', 1, ['sha3_32', '_sub']]], typ=BaseType('num'))
    if out_type == 'num':
        result = ['clamp',
                     ['mload', MINNUM_POS],
                     ['div', '_el1', ['exp', 256, ['sub', 32, '_len']]],
                     ['mload', MAXNUM_POS]]
    elif out_type == 'num256':
        result = ['div', '_el1', ['exp', 256, ['sub', 32, '_len']]]
    return LLLnode.from_list(['with', '_sub', arg,
                                 ['with', '_el1', first_el_getter,
                                    ['with', '_len', ['clamp', 0, lengetter, 32],
                                       ['seq',
                                          ['assert', ['or', ['iszero', '_len'], ['div', '_el1', ['exp', 256, 31]]]],
                                          result]]]],
                             typ=BaseType(out_type))

def get_length(arg):
    if arg.location == "calldata":
        return LLLnode.from_list(['calldataload', ['add', 4, arg]], typ=BaseType('num'))
    elif arg.location == "memory":
        return LLLnode.from_list(['mload', arg], typ=BaseType('num'))
    elif arg.location == "storage":
        return LLLnode.from_list(['sload', ['sha3_32', arg]], typ=BaseType('num'))
