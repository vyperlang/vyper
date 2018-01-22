import ast
import copy

from .exceptions import InvalidTypeException
from .utils import (
    base_types,
    ceil32,
    is_varname_valid,
    valid_units,
)


# Pretty-print a unit (eg. wei/seconds**2)
def print_unit(unit):
    if unit is None:
        return '*'
    if not isinstance(unit, dict):
        return unit
    pos = ''
    for k in sorted([x for x in unit.keys() if unit[x] > 0]):
        if unit[k] > 1:
            pos += '*' + k + '**' + str(unit[k])
        else:
            pos += '*' + k
    neg = ''
    for k in sorted([x for x in unit.keys() if unit[x] < 0]):
        if unit[k] < -1:
            neg += '/' + k + '**' + str(-unit[k])
        else:
            neg += '/' + k
    if pos and neg:
        return pos[1:] + neg
    elif neg:
        return '1' + neg
    else:
        return pos[1:]


# Multiply or divide two units by each other
def combine_units(unit1, unit2, div=False):
    o = {k: v for k, v in (unit1 or {}).items()}
    for k, v in (unit2 or {}).items():
        o[k] = o.get(k, 0) + v * (-1 if div else 1)
    return {k: v for k, v in o.items() if v}


# Data structure for a type
class NodeType():
    pass


# Data structure for a type that representsa 32-byte object
class BaseType(NodeType):

    def __init__(self, typ, unit=False, positional=False, override_signature=False):
        self.typ = typ
        self.unit = {} if unit is False else unit
        self.positional = positional
        self.override_signature = override_signature

    def __eq__(self, other):
        return other.__class__ == BaseType and self.typ == other.typ and self.unit == other.unit and self.positional == other.positional

    def __repr__(self):
        subs = []
        if self.unit != {}:
            subs.append(print_unit(self.unit))
        if self.positional:
            subs.append('positional')
        return str(self.typ) + (('(' + ', '.join(subs) + ')') if subs else '')


# Data structure for a byte array
class ByteArrayType(NodeType):
    def __init__(self, maxlen):
        self.maxlen = maxlen

    def __eq__(self, other):
        return other.__class__ == ByteArrayType and self.maxlen == other.maxlen

    def __repr__(self):
        return 'bytes <= %d' % self.maxlen


# Data structure for a list with some fixed length
class ListType(NodeType):
    def __init__(self, subtype, count):
        self.subtype = subtype
        self.count = count

    def __eq__(self, other):
        return other.__class__ == ListType and other.subtype == self.subtype and other.count == self.count

    def __repr__(self):
        return repr(self.subtype) + '[' + str(self.count) + ']'


# Data structure for a key-value mapping
class MappingType(NodeType):
    def __init__(self, keytype, valuetype):
        if not isinstance(keytype, (BaseType, ByteArrayType)):
            raise Exception("Dictionary keys must be a base type")
        self.keytype = keytype
        self.valuetype = valuetype

    def __eq__(self, other):
        return other.__class__ == MappingType and other.keytype == self.keytype and other.valuetype == self.valuetype

    def __repr__(self):
        return repr(self.valuetype) + '[' + repr(self.keytype) + ']'


# Data structure for a struct, eg. {a: <type>, b: <type>}
class StructType(NodeType):
    def __init__(self, members):
        self.members = copy.copy(members)

    def __eq__(self, other):
        return other.__class__ == StructType and other.members == self.members

    def __repr__(self):
        return '{' + ', '.join([k + ': ' + repr(v) for k, v in self.members.items()]) + '}'


# Data structure for a list with heterogeneous types, eg. [num, bytes32, bytes]
class TupleType(NodeType):
    def __init__(self, members):
        self.members = copy.copy(members)

    def __eq__(self, other):
        return other.__class__ == StructType and other.members == self.members

    def __repr__(self):
        return '(' + ', '.join([repr(m) for m in self.members]) + ')'


# Data structure for the type used by None/null
class NullType(NodeType):
    def __eq__(self, other):
        return other.__class__ == NullType


# Convert type into common form used in ABI
def canonicalize_type(t, is_indexed=False):
    if isinstance(t, ByteArrayType):
        # Check to see if maxlen is small enough for events
        if is_indexed:
            return 'bytes{}'.format(t.maxlen)
        else:
            return 'bytes'
    if isinstance(t, ListType):
        if not isinstance(t.subtype, (ListType, BaseType)):
            raise Exception("List of byte arrays not allowed")
        return canonicalize_type(t.subtype) + "[%d]" % t.count
    if isinstance(t, TupleType):
        return "({})".format(
            ",".join(canonicalize_type(x) for x in t.subtypes)
        )
    if not isinstance(t, BaseType):
        raise Exception("Cannot canonicalize non-base type: %r" % t)
    num256_override = True if t.override_signature == 'num256' else False

    t = t.typ
    if t == 'num' and not num256_override:
        return 'int128'
    elif t == 'num' and num256_override:
        return 'uint256'
    elif t == 'decimal':
        return 'decimal10'
    elif t == 'bool':
        return 'bool'
    elif t == 'num256':
        return 'uint256'
    elif t == 'signed256':
        return 'int256'
    elif t == 'address' or t == 'bytes32':
        return t
    elif t == 'real':
        return 'real128x128'
    raise Exception("Invalid or unsupported type: " + repr(t))


def parse_abi_type(t):
    if t == 'int128':
        return 'num'
    elif t == 'decimal10':
        return 'decimal'
    elif t == 'bool':
        return 'bool'
    elif t == 'uint256':
        return 'num256'
    elif t == 'int256':
        return 'signed256'
    elif t in ('address', 'bytes32'):
        return t
    raise Exception("Invalid or unsupported type: " + repr(t))


# Special types
special_types = {
    'timestamp': BaseType('num', {'sec': 1}, True),
    'timedelta': BaseType('num', {'sec': 1}, False),
    'currency_value': BaseType('num', {'currency': 1}, False),
    'currency1_value': BaseType('num', {'currency1': 1}, False),
    'currency2_value': BaseType('num', {'currency2': 1}, False),
    'wei_value': BaseType('num', {'wei': 1}, False),
}


# Parse an expression representing a unit
def parse_unit(item):
    if isinstance(item, ast.Name):
        if item.id not in valid_units:
            raise InvalidTypeException("Invalid base unit", item)
        return {item.id: 1}
    elif isinstance(item, ast.Num) and item.n == 1:
        return {}
    elif not isinstance(item, ast.BinOp):
        raise InvalidTypeException("Invalid unit expression", item)
    elif isinstance(item.op, ast.Mult):
        left, right = parse_unit(item.left), parse_unit(item.right)
        return combine_units(left, right)
    elif isinstance(item.op, ast.Div):
        left, right = parse_unit(item.left), parse_unit(item.right)
        return combine_units(left, right, div=True)
    elif isinstance(item.op, ast.Pow):
        if not isinstance(item.left, ast.Name):
            raise InvalidTypeException("Can only raise a base type to an exponent", item)
        if not isinstance(item.right, ast.Num) or not isinstance(item.right.n, int) or item.right.n <= 0:
            raise InvalidTypeException("Exponent must be positive integer", item)
        return {item.left.id: item.right.n}
    else:
        raise InvalidTypeException("Invalid unit expression", item)


# Parses an expression representing a type. Annotation refers to whether
# the type is to be located in memory or storage
def parse_type(item, location, sigs={}):
    # Base types, eg. num
    if isinstance(item, ast.Name):
        if item.id in base_types:
            return BaseType(item.id)
        elif item.id in special_types:
            return special_types[item.id]
        else:
            raise InvalidTypeException("Invalid base type: " + item.id, item)
    # Units, eg. num (1/sec) or contracts
    elif isinstance(item, ast.Call):
        # Contract_types
        if item.func.id == 'contract' or item.func.id == 'address':
            if sigs and item.args[0].id in sigs:
                return BaseType('address', item.args[0].id)
            else:
                raise InvalidTypeException('Invalid contract declaration')
        if not isinstance(item.func, ast.Name):
            raise InvalidTypeException("Malformed unit type:", item)
        base_type = item.func.id
        if base_type not in ('num', 'decimal'):
            raise InvalidTypeException("You must use num, decimal, address, contract, \
                for variable declarations and indexed for logging topics ", item)
        if len(item.args) == 0:
            raise InvalidTypeException("Malformed unit type", item)
        if isinstance(item.args[-1], ast.Name) and item.args[-1].id == "positional":
            positional = True
            argz = item.args[:-1]
        else:
            positional = False
            argz = item.args
        if len(argz) != 1:
            raise InvalidTypeException("Malformed unit type", item)
        # Check for num256 to num casting
        if item.func.id == 'num' and getattr(item.args[0], 'id', '') == 'num256':
            return BaseType('num', override_signature='num256')
        unit = parse_unit(argz[0])
        return BaseType(base_type, unit, positional)
    # Subscripts
    elif isinstance(item, ast.Subscript):
        if 'value' not in vars(item.slice):
            raise InvalidTypeException("Array access must access a single element, not a slice", item)
        # Fixed size lists, eg. num[100]
        elif isinstance(item.slice.value, ast.Num):
            if not isinstance(item.slice.value.n, int) or item.slice.value.n <= 0:
                raise InvalidTypeException("Arrays must have a positive integral number of elements", item.slice.value)
            return ListType(parse_type(item.value, location), item.slice.value.n)
        # Mappings, eg. num[address]
        else:
            if location == 'memory':
                raise InvalidTypeException("No mappings allowed for in-memory types, only fixed-size arrays", item)
            keytype = parse_type(item.slice.value, None)
            if not isinstance(keytype, (BaseType, ByteArrayType)):
                raise InvalidTypeException("Mapping keys must be base or bytes types", item.slice.value)
            return MappingType(keytype, parse_type(item.value, location))
    # Dicts, used to represent mappings, eg. {uint: uint}. Key must be a base type
    elif isinstance(item, ast.Dict):
        o = {}
        for key, value in zip(item.keys, item.values):
            if not isinstance(key, ast.Name) or not is_varname_valid(key.id):
                raise InvalidTypeException("Invalid member variable for struct", key)
            o[key.id] = parse_type(value, location)
        return StructType(o)
    elif isinstance(item, ast.Compare):
        if len(item.ops) != 1 or not isinstance(item.ops[0], ast.LtE):
            raise InvalidTypeException("Invalid type", item)
        if not isinstance(item.left, ast.Name) or item.left.id != "bytes":
            raise InvalidTypeException("Invalid type", item.left)
        if len(item.comparators) != 1 or not isinstance(item.comparators[0], ast.Num):
            raise InvalidTypeException("Byte array length must be a number", item)
        if not isinstance(item.comparators[0].n, int) or item.comparators[0].n <= 0:
            raise InvalidTypeException("Bad byte array length: %r" % item.comparators[0].n, item.comparators[0])
        return ByteArrayType(item.comparators[0].n)
    elif isinstance(item, ast.Tuple):
        members = [parse_type(x, location) for x in item.elts]
        return TupleType(members)
    else:
        raise InvalidTypeException("Invalid type: %r" % ast.dump(item), item)


# Gets the number of memory or storage keys needed to represent a given type
def get_size_of_type(typ):
    if isinstance(typ, BaseType):
        return 1
    elif isinstance(typ, ByteArrayType):
        return ceil32(typ.maxlen) // 32 + 2
    elif isinstance(typ, ListType):
        return get_size_of_type(typ.subtype) * typ.count
    elif isinstance(typ, MappingType):
        raise Exception("Maps are not supported for function arguments or outputs.")
    elif isinstance(typ, StructType):
        return sum([get_size_of_type(v) for v in typ.members.values()])
    elif isinstance(typ, TupleType):
        return sum([get_size_of_type(v) for v in typ.members])
    else:
        raise Exception("Unexpected type: %r" % repr(typ))


def set_default_units(typ):
    if isinstance(typ, BaseType):
        if typ.unit is None:
            return BaseType(typ.typ, {})
        else:
            return typ
    elif isinstance(typ, StructType):
        return StructType({k: set_default_units(v) for k, v in typ.members.items()})
    elif isinstance(typ, ListType):
        return ListType(set_default_units(typ.subtype), typ.count)
    elif isinstance(typ, MappingType):
        return MappingType(set_default_units(typ.keytype), set_default_units(typ.valuetype))
    else:
        return typ


# Checks that the units of frm can be seamlessly converted into the units of to
def are_units_compatible(frm, to):
    frm_unit = getattr(frm, 'unit', 0)
    to_unit = getattr(to, 'unit', 0)
    return frm_unit is None or (frm_unit == to_unit and frm.positional == to.positional)


# Is a type representing a number?
def is_numeric_type(typ):
    return isinstance(typ, BaseType) and typ.typ in ('num', 'decimal')


# Is a type representing some particular base type?
def is_base_type(typ, btypes):
    if not isinstance(btypes, tuple):
        btypes = (btypes, )
    return isinstance(typ, BaseType) and typ.typ in btypes
