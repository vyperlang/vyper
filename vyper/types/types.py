import abc
import copy
import warnings
from collections import OrderedDict
from typing import Any

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, InvalidType
from vyper.utils import BASE_TYPES, ceil32, check_valid_varname


# Data structure for a type
class NodeType(abc.ABC):
    def __eq__(self, other: Any) -> bool:
        return type(self) is type(other) and self.eq(other)

    @abc.abstractmethod
    def eq(self, other: "NodeType") -> bool:  # pragma: no cover
        """
        Checks whether or not additional properties of a ``NodeType`` subclass
        instance make it equal to another instance of the same type.
        """
        pass


# Data structure for a type that represents a 32-byte object
class BaseType(NodeType):
    def __init__(
        self, typ, unit=False, positional=False, override_signature=False, is_literal=False
    ):
        self.typ = typ
        if unit or positional:
            raise CompilerPanic("Units are no longer supported")
        self.override_signature = override_signature
        self.is_literal = is_literal

    def eq(self, other):
        return self.typ == other.typ

    def __repr__(self):
        return str(self.typ)


class InterfaceType(BaseType):
    def __init__(self, name):
        super().__init__("address")
        self.name = name

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BaseType) and other.typ == "address"


class ByteArrayLike(NodeType):
    def __init__(self, maxlen, is_literal=False):
        self.maxlen = maxlen
        self.is_literal = is_literal

    def eq(self, other):
        return self.maxlen == other.maxlen

    def eq_base(self, other):
        return type(self) is type(other)


class StringType(ByteArrayLike):
    def __repr__(self):
        return f"String[{self.maxlen}]"


# Data structure for a byte array
class ByteArrayType(ByteArrayLike):
    def __repr__(self):
        return f"Bytes[{self.maxlen}]"


# Data structure for a list with some fixed length
class ListType(NodeType):
    def __init__(self, subtype, count, is_literal=False):
        self.subtype = subtype
        self.count = count
        self.is_literal = is_literal

    def eq(self, other):
        return other.subtype == self.subtype and other.count == self.count

    def __repr__(self):
        return repr(self.subtype) + "[" + str(self.count) + "]"


# Data structure for a key-value mapping
class MappingType(NodeType):
    def __init__(self, keytype, valuetype):
        if not isinstance(keytype, (BaseType, ByteArrayLike)):
            raise InvalidType("Dictionary keys must be a base type")
        self.keytype = keytype
        self.valuetype = valuetype

    def eq(self, other):
        return other.keytype == self.keytype and other.valuetype == self.valuetype

    def __repr__(self):
        return "HashMap[" + repr(self.valuetype) + ", " + repr(self.keytype) + "]"


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
        prefix = "struct " + self.name + ": " if self.name else ""
        return prefix + "{" + ", ".join([k + ": " + repr(v) for k, v in self.members.items()]) + "}"

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
        return "(" + ", ".join([repr(m) for m in self.members]) + ")"

    def tuple_items(self):
        return list(enumerate(self.members))


# Convert type into common form used in ABI
def canonicalize_type(t, is_indexed=False):
    if isinstance(t, ByteArrayLike):
        # Check to see if maxlen is small enough for events
        byte_type = "string" if isinstance(t, StringType) else "bytes"
        return byte_type

    if isinstance(t, ListType):
        if not isinstance(t.subtype, (ListType, BaseType)):
            raise InvalidType(f"List of {t.subtype}s not allowed")
        return canonicalize_type(t.subtype) + f"[{t.count}]"

    if isinstance(t, TupleLike):
        return f"({','.join(canonicalize_type(x) for x in t.tuple_members())})"

    if not isinstance(t, BaseType):
        raise InvalidType(f"Cannot canonicalize non-base type: {t}")

    t = t.typ
    if t in ("int128", "uint256", "bool", "address", "bytes32"):
        return t
    elif t == "decimal":
        return "fixed168x10"

    raise InvalidType(f"Invalid or unsupported type: {repr(t)}")


def make_struct_type(name, location, members, custom_structs):
    o = OrderedDict()

    for key, value in members:
        if not isinstance(key, vy_ast.Name):
            raise InvalidType(
                f"Invalid member variable for struct {key.id}, expected a name.", key,
            )
        check_valid_varname(
            key.id, custom_structs, "Invalid member variable for struct",
        )
        o[key.id] = parse_type(value, location, custom_structs=custom_structs)

    return StructType(o, name)


# Parses an expression representing a type. Annotation refers to whether
# the type is to be located in memory or storage
def parse_type(item, location, sigs=None, custom_structs=None):
    # Base and custom types, e.g. num
    if isinstance(item, vy_ast.Name):
        if item.id in BASE_TYPES:
            return BaseType(item.id)
        elif (custom_structs is not None) and (item.id in custom_structs):
            return make_struct_type(item.id, location, custom_structs[item.id], custom_structs,)
        else:
            raise InvalidType("Invalid base type: " + item.id, item)
    # Units, e.g. num (1/sec) or contracts
    elif isinstance(item, vy_ast.Call) and isinstance(item.func, vy_ast.Name):
        # Contract_types
        if item.func.id == "address":
            if sigs and item.args[0].id in sigs:
                return InterfaceType(item.args[0].id)
        # Struct types
        if (custom_structs is not None) and (item.func.id in custom_structs):
            return make_struct_type(item.id, location, custom_structs[item.id], custom_structs,)
        raise InvalidType("Units are no longer supported", item)
    # Subscripts
    elif isinstance(item, vy_ast.Subscript):
        # Fixed size lists or bytearrays, e.g. num[100]
        if isinstance(item.slice.value, vy_ast.Int):
            n_val = item.slice.value.n
            if not isinstance(n_val, int) or n_val <= 0:
                raise InvalidType(
                    "Arrays / ByteArrays must have a positive integral number of elements",
                    item.slice.value,
                )
            # ByteArray
            if getattr(item.value, "id", None) == "Bytes":
                return ByteArrayType(n_val)
            elif getattr(item.value, "id", None) == "String":
                return StringType(n_val)
            # List
            else:
                return ListType(
                    parse_type(item.value, location, custom_structs=custom_structs,), n_val,
                )
        elif item.value.id in ("HashMap",) and isinstance(item.slice.value, vy_ast.Tuple):
            keytype = parse_type(item.slice.value.elements[0], None, custom_structs=custom_structs,)
            return MappingType(
                keytype,
                parse_type(item.slice.value.elements[1], location, custom_structs=custom_structs,),
            )
        # Mappings, e.g. num[address]
        else:
            raise InvalidType("Unknown list type.", item)

    # Dicts, used to represent mappings, e.g. {uint: uint}. Key must be a base type
    elif isinstance(item, vy_ast.Dict):
        warnings.warn(
            "Anonymous structs have been removed in" " favor of named structs, see VIP300",
            DeprecationWarning,
        )
        raise InvalidType("Invalid type", item)
    elif isinstance(item, vy_ast.Tuple):
        members = [parse_type(x, location, custom_structs=custom_structs) for x in item.elements]
        return TupleType(members)
    else:
        raise InvalidType("Invalid type", item)


# Gets the maximum number of memory or storage keys needed to ABI-encode
# a given type
def get_size_of_type(typ):
    if isinstance(typ, BaseType):
        return 1
    elif isinstance(typ, ByteArrayLike):
        # 1 word for offset (in static section), 1 word for length,
        # up to maxlen words for actual data.
        return ceil32(typ.maxlen) // 32 + 2
    elif isinstance(typ, ListType):
        return get_size_of_type(typ.subtype) * typ.count
    elif isinstance(typ, MappingType):
        raise InvalidType("Maps are not supported for function arguments or outputs.")
    elif isinstance(typ, TupleLike):
        return sum([get_size_of_type(v) for v in typ.tuple_members()])
    else:
        raise InvalidType(f"Can not get size of type, Unexpected type: {repr(typ)}")


# amount of space a type takes in the static section of its ABI encoding
def get_static_size_of_type(typ):
    if isinstance(typ, BaseType):
        return 1
    elif isinstance(typ, ByteArrayLike):
        return 1
    elif isinstance(typ, ListType):
        return get_size_of_type(typ.subtype) * typ.count
    elif isinstance(typ, MappingType):
        raise InvalidType("Maps are not supported for function arguments or outputs.")
    elif isinstance(typ, TupleLike):
        return sum([get_size_of_type(v) for v in typ.tuple_members()])
    else:
        raise InvalidType(f"Can not get size of type, Unexpected type: {repr(typ)}")


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
        raise InvalidType(f"Unexpected type: {repr(typ)}")


def get_type(input):
    if not hasattr(input, "typ"):
        typ, len = "num_literal", 32
    elif hasattr(input.typ, "maxlen"):
        typ, len = "Bytes", input.typ.maxlen
    else:
        typ, len = input.typ.typ, 32
    return typ, len


# Is a type representing a number?
def is_numeric_type(typ):
    return isinstance(typ, BaseType) and typ.typ in ("int128", "uint256", "decimal")


# Is a type representing some particular base type?
def is_base_type(typ, btypes):
    if not isinstance(btypes, tuple):
        btypes = (btypes,)
    return isinstance(typ, BaseType) and typ.typ in btypes
