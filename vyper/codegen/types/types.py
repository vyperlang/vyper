import abc
import copy
from collections import OrderedDict
from typing import Any

from vyper import ast as vy_ast
from vyper.exceptions import ArgumentException, CompilerPanic, InvalidType
from vyper.utils import BASE_TYPES, ceil32


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

    @property
    @abc.abstractmethod
    def memory_bytes_required(self) -> int:
        """
        Returns the number of bytes required to allocate in memory for this type
        """
        raise InvalidType(f"Unexpected type: {self}")

    @property
    def storage_size_in_words(self) -> int:
        """
        Returns the number of words required to allocate in storage for this type
        """
        r = self.memory_bytes_required
        if r % 32 != 0:
            raise CompilerPanic("Memory bytes must be multiple of 32")
        return r // 32


# Data structure for a type that represents a 32-byte object
class BaseType(NodeType):
    def __init__(
        self, typ, unit=False, positional=False, override_signature=False, is_literal=False
    ):
        self.typ = typ
        # TODO remove dead arguments
        if unit or positional:
            raise CompilerPanic("Units are no longer supported")
        self.override_signature = override_signature  # TODO dead
        self.is_literal = is_literal

    def eq(self, other):
        return self.typ == other.typ

    def __repr__(self):
        return str(self.typ)

    @property
    def memory_bytes_required(self):
        return 32


class InterfaceType(BaseType):
    def __init__(self, name):
        super().__init__("address")
        self.name = name

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BaseType) and other.typ == "address"

    @property
    def memory_bytes_required(self):
        return 32


class ByteArrayLike(NodeType):
    def __init__(self, maxlen, is_literal=False):
        self.maxlen = maxlen
        self.is_literal = is_literal

    def eq(self, other):
        return self.maxlen == other.maxlen

    def eq_base(self, other):
        return type(self) is type(other)

    @property
    def memory_bytes_required(self):
        return ceil32(self.maxlen) + 32 * DYNAMIC_ARRAY_OVERHEAD


class StringType(ByteArrayLike):
    def __repr__(self):
        return f"String[{self.maxlen}]"


# Data structure for a byte array
class ByteArrayType(ByteArrayLike):
    def __repr__(self):
        return f"Bytes[{self.maxlen}]"


# Data structure for a static array
class ArrayLike(NodeType):
    def __init__(self, subtype, count, is_literal=False):
        self.subtype = subtype
        self.count = count
        self.is_literal = is_literal

    def eq(self, other):
        return other.subtype == self.subtype and other.count == self.count


# Data structure for a static array
class SArrayType(ArrayLike):
    def __repr__(self):
        return f"{self.subtype}[{self.count}]"

    @property
    def memory_bytes_required(self):
        return self.count * self.subtype.memory_bytes_required


# Data structure for a dynamic array
class DArrayType(ArrayLike):
    def __repr__(self):
        return f"DynArray[{self.subtype}, {self.count}]"

    @property
    def memory_bytes_required(self):
        return DYNAMIC_ARRAY_OVERHEAD * 32 + self.count * self.subtype.memory_bytes_required


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

    @property
    def memory_bytes_required(self):
        raise InvalidType("Maps are not supported for function arguments or outputs.")


# Type which has heterogeneous members, i.e. Tuples and Structs
class TupleLike(NodeType):
    def tuple_members(self):
        return [v for (_k, v) in self.tuple_items()]

    def tuple_keys(self):
        return [k for (k, _v) in self.tuple_items()]

    def tuple_items(self):
        raise NotImplementedError("compiler panic!: tuple_items must be implemented by TupleLike")

    @property
    def memory_bytes_required(self):
        return sum([t.memory_bytes_required for t in self.tuple_members()])


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
        if self.name:
            return "struct " + self.name
        else:
            # Anonymous struct
            return (
                "struct {" + ", ".join([k + ": " + repr(v) for k, v in self.members.items()]) + "}"
            )

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

    if isinstance(t, ArrayLike):
        if not isinstance(t.subtype, (ArrayLike, BaseType, StructType)):
            raise InvalidType(f"List of {t.subtype} not allowed")
        if isinstance(t, SArrayType):
            return canonicalize_type(t.subtype) + f"[{t.count}]"
        if isinstance(t, DArrayType):
            return canonicalize_type(t.subtype) + "[]"
        raise CompilerPanic(f"unhandled type {type(t)}")

    if isinstance(t, TupleLike):
        return f"({','.join(canonicalize_type(x) for x in t.tuple_members())})"

    if not isinstance(t, BaseType):
        raise InvalidType(f"Cannot canonicalize non-base type: {t}")

    t = t.typ
    if t in ("int128", "int256", "uint8", "uint256", "bool", "address", "bytes32"):
        return t
    elif t == "decimal":
        return "fixed168x10"

    raise InvalidType(f"Invalid or unsupported type: {repr(t)}")


def make_struct_type(name, sigs, members, custom_structs):
    o = OrderedDict()

    for key, value in members:
        if not isinstance(key, vy_ast.Name):
            raise InvalidType(
                f"Invalid member variable for struct {key.id}, expected a name.",
                key,
            )
        o[key.id] = parse_type(value, sigs=sigs, custom_structs=custom_structs)

    return StructType(o, name)


# Parses an expression representing a type. Annotation refers to whether
# the type is to be located in memory or storage
# TODO: rename me to "lll_type_from_annotation"
def parse_type(item, sigs=None, custom_structs=None):
    def _sanity_check(x):
        assert x, "typechecker missed this"

    # Base and custom types, e.g. num
    if isinstance(item, vy_ast.Name):
        if item.id in BASE_TYPES:
            return BaseType(item.id)
        elif (sigs is not None) and item.id in sigs:
            return InterfaceType(item.id)
        elif (custom_structs is not None) and (item.id in custom_structs):
            return make_struct_type(
                item.id,
                sigs,
                custom_structs[item.id],
                custom_structs,
            )
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
            return make_struct_type(
                item.id,
                sigs,
                custom_structs[item.id],
                custom_structs,
            )
        if item.func.id == "immutable":
            if len(item.args) != 1:
                # is checked earlier but just for sanity, verify
                # immutable call is given only one argument
                raise ArgumentException("Invalid number of arguments to `immutable`", item)
            return BaseType(item.args[0].id)

        raise InvalidType("Units are no longer supported", item)

    # Subscripts
    elif isinstance(item, vy_ast.Subscript):
        # Fixed size lists or bytearrays, e.g. num[100]
        if isinstance(item.slice.value, vy_ast.Int):
            length = item.slice.value.n
            _sanity_check(isinstance(length, int) and length > 0)

            # ByteArray
            if getattr(item.value, "id", None) == "Bytes":
                return ByteArrayType(length)
            elif getattr(item.value, "id", None) == "String":
                return StringType(length)
            # List
            else:
                value_type = parse_type(
                    item.value,
                    sigs,
                    custom_structs=custom_structs,
                )
                return SArrayType(value_type, length)
        elif item.value.id == "DynArray":

            _sanity_check(isinstance(item.slice.value, vy_ast.Tuple))
            length = item.slice.value.elements[1].n
            _sanity_check(isinstance(length, int) and length > 0)

            value_type_annotation = item.slice.value.elements[0]
            value_type = parse_type(value_type_annotation, sigs, custom_structs=custom_structs)

            return DArrayType(value_type, length)

        elif item.value.id in ("HashMap",) and isinstance(item.slice.value, vy_ast.Tuple):
            keytype = parse_type(
                item.slice.value.elements[0],
                sigs=sigs,
                custom_structs=custom_structs,
            )
            return MappingType(
                keytype,
                parse_type(
                    item.slice.value.elements[1],
                    sigs,
                    custom_structs=custom_structs,
                ),
            )
        # Mappings, e.g. num[address]
        else:
            raise InvalidType("Unknown list type.", item)
    elif isinstance(item, vy_ast.Tuple):
        members = [parse_type(x, custom_structs=custom_structs) for x in item.elements]
        return TupleType(members)
    else:
        raise InvalidType("Invalid type", item)


# dynamic array overhead, in words.
DYNAMIC_ARRAY_OVERHEAD = 1


def get_type_for_exact_size(n_bytes):
    """Create a type which will take up exactly n_bytes. Used for allocating internal buffers.

    Parameters:
      n_bytes: the number of bytes to allocate
    Returns:
      type: A type which can be passed to context.new_variable
    """
    return ByteArrayType(n_bytes - 32 * DYNAMIC_ARRAY_OVERHEAD)


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
    return isinstance(typ, BaseType) and typ.typ in (
        "int128",
        "int256",
        "uint8",
        "uint256",
        "decimal",
    )


def is_signed_num(typ):
    if not is_numeric_type(typ):
        return None
    return typ.typ.startswith("u")


# Is a type representing some particular base type?
def is_base_type(typ, btypes):
    if not isinstance(btypes, tuple):
        btypes = (btypes,)
    return isinstance(typ, BaseType) and typ.typ in btypes
