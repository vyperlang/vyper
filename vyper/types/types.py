import abc
from collections import (
    OrderedDict,
)
import copy
from typing import (
    Any,
)
import warnings

from vyper import ast
from vyper.exceptions import (
    InvalidTypeException,
)
from vyper.utils import (
    base_types,
    ceil32,
    check_valid_varname,
    valid_units,
)


def unit_from_type(typ):
    try:
        return typ.unit
    except AttributeError:
        return {}


# Pretty-print a unit (e. g. m/s)
# if unit_descriptions is provided humanizes it (e. g. Meter per Second)
def print_unit(unit, unit_descriptions=None):
    def humanize_power(power):
        if unit_descriptions and power == 2:
            return ' squared'
        else:
            return '**' + str(power)

    def humanize_unit(unit_key):
        try:
            return unit_descriptions[unit_key]
        except (TypeError, KeyError):
            # unit_descriptions is None or missing unit_key
            return unit_key

    if unit_descriptions:
        mul = '-'
        div = ' per '
    else:
        mul = '*'
        div = '/'

    if unit is None:
        return '*'

    if not isinstance(unit, dict):
        return unit

    pos = ''
    for k in sorted([x for x in unit.keys() if unit[x] > 0]):
        if unit[k] > 1:
            pos += mul + humanize_unit(k) + humanize_power(unit[k])
        else:
            pos += mul + humanize_unit(k)

    neg = ''
    for k in sorted([x for x in unit.keys() if unit[x] < 0]):
        if unit[k] < -1:
            neg += div + humanize_unit(k) + humanize_power(-unit[k])
        else:
            neg += div + humanize_unit(k)

    if pos and neg:
        return pos[1:] + neg
    elif neg:
        return '1' + neg
    else:
        return pos[1:]


def delete_unit_if_empty(abi_dict):
    try:
        if not abi_dict['unit']:
            del abi_dict['unit']
    except KeyError:
        # unit is already removed
        pass


# Multiply or divide two units by each other
def combine_units(unit1, unit2, div=False):
    o = {k: v for k, v in (unit1 or {}).items()}
    for k, v in (unit2 or {}).items():
        o[k] = o.get(k, 0) + v * (-1 if div else 1)
    return {k: v for k, v in o.items() if v}


# Data structure for a type
class NodeType(abc.ABC):
    def __eq__(self, other: Any) -> bool:
        return type(self) is type(other) and self.eq(other)

    @abc.abstractmethod
    def eq(self, other: 'NodeType') -> bool:  # pragma: no cover
        """
        Checks whether or not additional properties of a ``NodeType`` subclass
        instance make it equal to another instance of the same type.
        """
        pass


# Data structure for a type that represents a 32-byte object
class BaseType(NodeType):
    def __init__(self,
                 typ,
                 unit=False,
                 positional=False,
                 override_signature=False,
                 is_literal=False):
        self.typ = typ
        self.unit = {} if not unit else unit
        self.positional = positional
        self.override_signature = override_signature
        self.is_literal = is_literal

    def eq(self, other):
        return (
            self.typ == other.typ and self.unit == other.unit
        ) and self.positional == other.positional

    def __repr__(self):
        subs = []
        if self.unit != {}:
            subs.append(print_unit(self.unit))
        if self.positional:
            subs.append('positional')
        return str(self.typ) + (('(' + ', '.join(subs) + ')') if subs else '')


class ContractType(BaseType):
    def __init__(self, name):
        super().__init__('address', name)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BaseType) and other.typ == 'address'


class ByteArrayLike(NodeType):
    def __init__(self, maxlen):
        self.maxlen = maxlen

    def eq(self, other):
        return self.maxlen == other.maxlen

    def eq_base(self, other):
        return type(self) is type(other)


class StringType(ByteArrayLike):
    def __repr__(self):
        return 'string[%d]' % self.maxlen


# Data structure for a byte array
class ByteArrayType(ByteArrayLike):
    def __repr__(self):
        return 'bytes[%d]' % self.maxlen


# Data structure for a list with some fixed length
class ListType(NodeType):
    def __init__(self, subtype, count, is_literal=False):
        self.subtype = subtype
        self.count = count
        self.is_literal = is_literal

    def eq(self, other):
        return other.subtype == self.subtype and other.count == self.count

    def __repr__(self):
        return repr(self.subtype) + '[' + str(self.count) + ']'


# Data structure for a key-value mapping
class MappingType(NodeType):
    def __init__(self, keytype, valuetype):
        if not isinstance(keytype, (BaseType, ByteArrayLike)):
            raise Exception("Dictionary keys must be a base type")
        self.keytype = keytype
        self.valuetype = valuetype

    def eq(self, other):
        return other.keytype == self.keytype and other.valuetype == self.valuetype

    def __repr__(self):
        return 'map(' + repr(self.valuetype) + ', ' + repr(self.keytype) + ')'


# Type which has heterogeneous members, i.e. Tuples and Structs
class TupleLike(NodeType):
    def tuple_members(self):
        return [v for (_k, v) in self.tuple_items()]

    def tuple_keys(self):
        return [k for (k, _v) in self.tuple_items()]

    def tuple_items(self):
        raise NotImplementedError("compiler panic!: tuple_items must be implemented by TupleLike")


# Data structure for a struct, e.g. {a: <type>, b: <type>}
# struct can be named or anonymous. name=None indicates anonymous.
class StructType(TupleLike):
    def __init__(self, members, name, is_literal=False):
        self.members = copy.copy(members)
        self.name = name
        self.is_literal = is_literal

    def eq(self, other):
        return other.name == self.name and other.members == self.members

    def __repr__(self):
        prefix = 'struct ' + self.name + ': ' if self.name else ''
        return prefix + '{' + ', '.join([k + ': ' + repr(v) for k, v in self.members.items()]) + '}'

    def tuple_items(self):
        return list(self.members.items())


# Data structure for a list with heterogeneous types, e.g. [int128, bytes32, bytes]
class TupleType(TupleLike):
    def __init__(self, members, is_literal=False):
        self.members = copy.copy(members)
        self.is_literal = is_literal

    def eq(self, other):
        return other.members == self.members

    def __repr__(self):
        return '(' + ', '.join([repr(m) for m in self.members]) + ')'

    def tuple_items(self):
        return list(enumerate(self.members))


# Data structure for the type used by None/null
class NullType(NodeType):
    def eq(self, other):
        return True


# Convert type into common form used in ABI
def canonicalize_type(t, is_indexed=False):
    if isinstance(t, ByteArrayLike):
        # Check to see if maxlen is small enough for events
        byte_type = 'string' if isinstance(t, StringType) else 'bytes'
        if is_indexed:
            return '{}{}'.format(byte_type, t.maxlen)
        else:
            return '{}'.format(byte_type)

    if isinstance(t, ListType):
        if not isinstance(t.subtype, (ListType, BaseType)):
            raise Exception("List of byte arrays not allowed")
        return canonicalize_type(t.subtype) + "[%d]" % t.count

    if isinstance(t, TupleLike):
        return "({})".format(
            ",".join(canonicalize_type(x) for x in t.tuple_members())
        )

    if not isinstance(t, BaseType):
        raise Exception("Cannot canonicalize non-base type: %r" % t)

    t = t.typ
    if t in ('int128', 'uint256', 'bool', 'address', 'bytes32'):
        return t
    elif t == 'decimal':
        return 'fixed168x10'

    raise Exception("Invalid or unsupported type: " + repr(t))


# Special types
special_types = {
    'timestamp': BaseType('uint256', {'sec': 1}, True),
    'timedelta': BaseType('uint256', {'sec': 1}, False),
    'wei_value': BaseType('uint256', {'wei': 1}, False),
}


# Parse an expression representing a unit
def parse_unit(item, custom_units):
    if isinstance(item, ast.Name):
        if (item.id not in valid_units) and (custom_units is not None) and (item.id not in custom_units):  # noqa: E501
            raise InvalidTypeException("Invalid base unit", item)
        return {item.id: 1}
    elif isinstance(item, ast.Num) and item.n == 1:
        return {}
    elif not isinstance(item, ast.BinOp):
        raise InvalidTypeException("Invalid unit expression", item)
    elif isinstance(item.op, ast.Mult):
        left, right = parse_unit(item.left, custom_units), parse_unit(item.right, custom_units)
        return combine_units(left, right)
    elif isinstance(item.op, ast.Div):
        left, right = parse_unit(item.left, custom_units), parse_unit(item.right, custom_units)
        return combine_units(left, right, div=True)
    elif isinstance(item.op, ast.Pow):
        if not isinstance(item.left, ast.Name):
            raise InvalidTypeException("Can only raise a base type to an exponent", item)
        if not isinstance(item.right, ast.Num) or not isinstance(item.right.n, int) or item.right.n <= 0:  # noqa: E501
            raise InvalidTypeException("Exponent must be positive integer", item)
        return {item.left.id: item.right.n}
    else:
        raise InvalidTypeException("Invalid unit expression", item)


def make_struct_type(name, location, members, custom_units, custom_structs, constants):
    o = OrderedDict()

    for key, value in members:
        if not isinstance(key, ast.Name):
            raise InvalidTypeException(
                "Invalid member variable for struct %r, expected a name." % key.id,
                key,
            )
        check_valid_varname(
            key.id,
            custom_units,
            custom_structs,
            constants,
            "Invalid member variable for struct",
        )
        o[key.id] = parse_type(
            value,
            location,
            custom_units=custom_units,
            custom_structs=custom_structs,
            constants=constants,
        )

    return StructType(o, name)


# Parses an expression representing a type. Annotation refers to whether
# the type is to be located in memory or storage
def parse_type(item, location, sigs=None, custom_units=None, custom_structs=None, constants=None):
    # Base and custom types, e.g. num
    if isinstance(item, ast.Name):
        if item.id in base_types:
            return BaseType(item.id)
        elif item.id in special_types:
            return special_types[item.id]
        elif (custom_structs is not None) and (item.id in custom_structs):
            return make_struct_type(
                item.id,
                location,
                custom_structs[item.id],
                custom_units,
                custom_structs,
                constants,
            )
        else:
            raise InvalidTypeException("Invalid base type: " + item.id, item)
    # Units, e.g. num (1/sec) or contracts
    elif isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
        # Mapping type.
        if item.func.id == 'map':
            if location == 'memory':
                raise InvalidTypeException(
                    "No mappings allowed for in-memory types, only fixed-size arrays",
                    item,
                )
            if len(item.args) != 2:
                raise InvalidTypeException(
                    "Mapping requires 2 valid positional arguments.",
                    item,
                )
            keytype = parse_type(
                item.args[0],
                None,
                custom_units=custom_units,
                custom_structs=custom_structs,
                constants=constants,
            )
            if not isinstance(keytype, (BaseType, ByteArrayLike)):
                raise InvalidTypeException("Mapping keys must be base or bytes/string types", item)
            return MappingType(
                keytype,
                parse_type(
                    item.args[1],
                    location,
                    custom_units=custom_units,
                    custom_structs=custom_structs,
                    constants=constants,
                ),
            )
        # Contract_types
        if item.func.id == 'address':
            if sigs and item.args[0].id in sigs:
                return ContractType(item.args[0].id)
        # Struct types
        if (custom_structs is not None) and (item.func.id in custom_structs):
            return make_struct_type(
                item.id,
                location,
                custom_structs[item.id],
                custom_units,
                custom_structs,
                constants,
            )
        if not isinstance(item.func, ast.Name):
            raise InvalidTypeException("Malformed unit type:", item)
        base_type = item.func.id
        if base_type not in ('int128', 'uint256', 'decimal', 'address'):
            raise InvalidTypeException("You must use int128, uint256, decimal, address, contract, \
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
        unit = parse_unit(argz[0], custom_units=custom_units)
        return BaseType(base_type, unit, positional)
    # Subscripts
    elif isinstance(item, ast.Subscript):
        if isinstance(item.slice, ast.Slice):
            raise InvalidTypeException(
                "Array / ByteArray access must access a single element, not a slice",
                item,
            )
        # Fixed size lists or bytearrays, e.g. num[100]
        is_constant_val = constants.ast_is_constant(item.slice.value)
        if isinstance(item.slice.value, ast.Num) or is_constant_val:
            n_val = (
                constants.get_constant(item.slice.value.id, context=None).value
                if is_constant_val
                else item.slice.value.n
            )
            if not isinstance(n_val, int) or n_val <= 0:
                raise InvalidTypeException(
                    "Arrays / ByteArrays must have a positive integral number of elements",
                    item.slice.value,
                )
            # ByteArray
            if getattr(item.value, 'id', None) == 'bytes':
                return ByteArrayType(n_val)
            elif getattr(item.value, 'id', None) == 'string':
                return StringType(n_val)
            # List
            else:
                return ListType(parse_type(
                    item.value,
                    location,
                    custom_units=custom_units,
                    custom_structs=custom_structs,
                    constants=constants,
                ), n_val)
        # Mappings, e.g. num[address]
        else:
            warnings.warn(
                "Mapping definitions using subscript have deprecated (see VIP564). "
                "Use map(type1, type2) instead.",
                DeprecationWarning
            )
            raise InvalidTypeException('Unknown list type.', item)

    # Dicts, used to represent mappings, e.g. {uint: uint}. Key must be a base type
    elif isinstance(item, ast.Dict):
        warnings.warn(
            "Anonymous structs have been removed in"
            " favor of named structs, see VIP300",
            DeprecationWarning
        )
        raise InvalidTypeException("Invalid type", item)
    elif isinstance(item, ast.Tuple):
        members = [
            parse_type(
                x,
                location,
                custom_units=custom_units,
                custom_structs=custom_structs,
                constants=constants
            ) for x in item.elts
        ]
        return TupleType(members)
    else:
        raise InvalidTypeException("Invalid type", item)


# Gets the number of memory or storage keys needed to represent a given type
def get_size_of_type(typ):
    if isinstance(typ, BaseType):
        return 1
    elif isinstance(typ, ByteArrayLike):
        return ceil32(typ.maxlen) // 32 + 2
    elif isinstance(typ, ListType):
        return get_size_of_type(typ.subtype) * typ.count
    elif isinstance(typ, MappingType):
        raise Exception("Maps are not supported for function arguments or outputs.")
    elif isinstance(typ, TupleLike):
        return sum([get_size_of_type(v) for v in typ.tuple_members()])
    else:
        raise Exception("Can not get size of type, Unexpected type: %r" % repr(typ))


# amount of space a type takes in the static section of its ABI encoding
def get_static_size_of_type(typ):
    if isinstance(typ, BaseType):
        return 1
    elif isinstance(typ, ByteArrayLike):
        return 1
    elif isinstance(typ, ListType):
        return get_size_of_type(typ.subtype) * typ.count
    elif isinstance(typ, MappingType):
        raise Exception("Maps are not supported for function arguments or outputs.")
    elif isinstance(typ, TupleLike):
        return sum([get_size_of_type(v) for v in typ.tuple_members()])
    else:
        raise Exception("Can not get size of type, Unexpected type: %r" % repr(typ))


# could be rewritten as get_static_size_of_type == get_size_of_type?
def has_dynamic_data(typ):
    if isinstance(typ, BaseType):
        return False
    elif isinstance(typ, ByteArrayLike):
        return True
    elif isinstance(typ, ListType):
        return has_dynamic_data(typ.subtype)
    elif isinstance(typ, TupleLike):
        return any([has_dynamic_data(v) for v in typ.tuple_members()])
    else:
        raise Exception("Unexpected type: %r" % repr(typ))


def get_type(input):
    if not hasattr(input, 'typ'):
        typ, len = 'num_literal', 32
    elif hasattr(input.typ, 'maxlen'):
        typ, len = 'bytes', input.typ.maxlen
    else:
        typ, len = input.typ.typ, 32
    return typ, len


# Checks that the units of frm can be seamlessly converted into the units of to
def are_units_compatible(frm, to):
    frm_unit = frm.unit
    to_unit = to.unit
    return frm_unit == {} or (frm_unit == to_unit and frm.positional == to.positional)


# Is a type representing a number?
def is_numeric_type(typ):
    return isinstance(typ, BaseType) and typ.typ in ('int128', 'uint256', 'decimal')


# Is a type representing some particular base type?
def is_base_type(typ, btypes):
    if not isinstance(btypes, tuple):
        btypes = (btypes, )
    return isinstance(typ, BaseType) and typ.typ in btypes
