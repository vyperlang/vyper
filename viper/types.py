import ast
from .opcodes import opcodes
import copy

# Available base types
base_types = ['num', 'decimal', 'bytes32', 'num256', 'signed256', 'bool', 'address']

# Valid base units
valid_units = ['currency', 'wei', 'currency1', 'currency2', 'sec', 'm', 'kg']

# Cannot be used for variable or member naming
reserved_words = ['int128', 'int256', 'uint256', 'address', 'bytes32',
                  'real', 'real128x128', 'if', 'for', 'while', 'until',
                  'pass', 'def', 'push', 'dup', 'swap', 'send', 'call',
                  'suicide', 'selfdestruct', 'assert', 'stop', 'throw',
                  'raise', 'init', '_init_', '___init___', '____init____',
                  'true', 'false', 'self', 'this', 'continue']

# Is a variable or member variable name valid?
def is_varname_valid(varname):
    if varname.lower() in base_types:
        return False
    if varname.lower() in reserved_words:
        return False
    if varname[0] == '~':
        return False
    if varname.upper() in opcodes:
        return False
    return True

# Pretty-print a unit (eg. wei/seconds^2)
def print_unit(unit):
    if unit is None:
        return '*'
    pos = ''
    for k in sorted([x for x in unit.keys() if unit[x] > 0]):
        if unit[k] > 1:
            pos += '*' + k + '^' + str(unit[k])
        else:
            pos += '*' + k
    neg = ''
    for k in sorted([x for x in unit.keys() if unit[x] < 0]):
        if unit[k] < -1:
            neg += '/' + k + '^' + str(-unit[k])
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
    def __init__(self, typ, unit=False, positional=False):
        self.typ = typ
        self.unit = {} if unit is False else unit
        self.positional = positional

    def __eq__(self, other):
        return other.__class__ == BaseType and self.typ == other.typ and self.unit == other.unit and self.positional == other.positional

    def __repr__(self):
        return '<' + str(self.typ) + ('>' if self.unit == {} else '> (' + print_unit(self.unit) + ')') + (' (positional) ' * self.positional)

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
        if not isinstance(keytype, BaseType):
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

# Data structure for a "multi" object with a mixed type
class MixedType(NodeType):
    def __eq__(self, other):
        return other.__class__ == MixedType

# Data structure for the type used by None/null
class NullType(NodeType):
    def __eq__(self, other):
        return other.__class__ == NullType

class InvalidTypeException(Exception):
    pass

class TypeMismatchException(Exception):
    pass

# Convert type into common form used in ABI
def canonicalize_type(t):
    if not isinstance(t, BaseType):
        raise Exception("Cannot canonicalize non-base type: %r" % t)
    t = t.typ
    if t == 'num':
        return 'int128'
    elif t == 'bool':
        return 'bool'
    elif t == 'num256':
        return 'int256'
    elif t == 'signed256':
        return 'uint256'
    elif t == 'address' or t == 'bytes32':
        return t
    elif t == 'real':
        return 'real128x128'
    raise Exception("Invalid or unsupported type: "+repr(t))

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
            raise InvalidTypeException("Invalid base unit: %r" % item.id)
        return {item.id: 1}
    elif isinstance(item, ast.Num) and item.n == 1:
        return {}
    elif not isinstance(item, ast.BinOp):
        raise InvalidTypeException("Invalid unit expression: %r" % ast.dump(item))
    elif isinstance(item.op, ast.Mult):
        left, right = parse_unit(item.left), parse_unit(item.right)
        return combine_units(left, right)
    elif isinstance(item.op, ast.Div):
        left, right = parse_unit(item.left), parse_unit(item.right)
        return combine_units(left, right, div=True)
    elif isinstance(item.op, ast.Pow):
        if not isinstance(item.left, ast.Name):
            raise InvalidTypeException("Can only raise a base type to an exponent")
        if not isinstance(item.right, ast.Num) or not isinstance(item.right.n, int) or item.right.n <= 0:
            raise InvalidTypeException("Exponent must be positive integer")
        return {item.left.id: item.right.n}
    else:
        raise InvalidTypeException("Invalid unit expression: %r" % ast.dump(item))

# Parses an expression representing a type. Annotation refers to whether
# the type is to be located in memory or storage
def parse_type(item, location):
    # Base types, eg. num
    if isinstance(item, ast.Name):
        if item.id in base_types:
            return BaseType(item.id)
        elif item.id in special_types:
            return special_types[item.id]
        else:
            raise InvalidTypeException("Invalid type: "+item.id)
    # Units, eg. num (1/sec)
    elif isinstance(item, ast.Call):
        if not isinstance(item.func, ast.Name):
            raise InvalidTypeException("Malformed unit type: %r" % ast.dump(item.func))
        base_type = item.func.id
        if base_type not in ('num', 'decimal'):
            raise Exception("Base type with units can only be num and decimal")
        if len(item.args) != 1:
            raise InvalidTypeException("Malformed unit type: %r" % ast.dump(item))
        unit = parse_unit(item.args[0])
        return BaseType(base_type, unit, False)
    # Subscripts
    elif isinstance(item, ast.Subscript):
        if 'value' not in vars(item.slice):
            raise InvalidTypeException("Array access must access a single element, not a slice")
        # Fixed size lists, eg. num[100]
        elif isinstance(item.slice.value, ast.Num):
            if not isinstance(item.slice.value.n, int) or item.slice.value.n <= 0:
                raise InvalidTypeException("Arrays must have a positive integral number of elements")
            return ListType(parse_type(item.value, location), item.slice.value.n)
        # Mappings, eg. num[address]
        elif isinstance(item.slice.value, ast.Name):
            if location == 'memory':
                raise InvalidTypeException("No mappings allowed for in-memory types, only fixed-size arrays") 
            keytype = parse_type(item.slice.value, None)
            if not isinstance(keytype, BaseType):
                raise Exception("Mapping keys must be base types")
            return MappingType(keytype, parse_type(item.value, location))
        else:
            raise InvalidTypeException("Arrays must be of the format type[num_of_elements] or type[key_type]")
    # Dicts, used to represent mappings, eg. {uint: uint}. Key must be a base type
    elif isinstance(item, ast.Dict):
        o = {} 
        for key, value in zip(item.keys, item.values):
            if not isinstance(key, ast.Name) or not is_varname_valid(key.id):
                raise InvalidTypeException("Invalid member variable for struct: %r" % vars(key).get('id', key))
            o[key.id] = parse_type(value, location)
        return StructType(o)
    else:
        raise InvalidTypeException("Invalid type: %r" % ast.dump(item))

# Gets the number of memory or storage keys needed to represent a given type
def get_size_of_type(typ):
    if isinstance(typ, BaseType):
        return 1
    if isinstance(typ, ListType):
        return get_size_of_type(typ.subtype) * typ.count
    elif isinstance(typ, MappingType):
        raise Exception("Type size infinite!")
    elif isinstance(typ, StructType):
        return sum([get_size_of_type(v) for v in typ.members.values()])
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
    return frm.unit is None or (frm.unit == to.unit and frm.positional == to.positional)

# Is a type representing a number?
def is_numeric_type(typ):
    return isinstance(typ, BaseType) and typ.typ in ('num', 'decimal')

# Is a type representing some particular base type?
def is_base_type(typ, btypes):
    if not isinstance(btypes, tuple):
        btypes = (btypes, )
    return isinstance(typ, BaseType) and typ.typ in btypes
