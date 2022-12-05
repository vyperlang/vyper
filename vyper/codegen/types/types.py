import abc
import copy
import re
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Tuple

from vyper import ast as vy_ast
from vyper.abi_types import (
    ABI_Address,
    ABI_Bool,
    ABI_Bytes,
    ABI_BytesM,
    ABI_DynamicArray,
    ABI_FixedMxN,
    ABI_GIntM,
    ABI_StaticArray,
    ABI_String,
    ABI_Tuple,
    ABIType,
)
from vyper.exceptions import ArgumentException, CompilerPanic, InvalidType
from vyper.utils import ceil32, int_bounds

# Available base types
UNSIGNED_INTEGER_TYPES = {f"uint{8*(i+1)}" for i in range(32)}
SIGNED_INTEGER_TYPES = {f"int{8*(i+1)}" for i in range(32)}
INTEGER_TYPES = UNSIGNED_INTEGER_TYPES | SIGNED_INTEGER_TYPES

BYTES_M_TYPES = {f"bytes{i+1}" for i in range(32)}
DECIMAL_TYPES = {"decimal"}


BASE_TYPES = INTEGER_TYPES | BYTES_M_TYPES | DECIMAL_TYPES | {"bool", "address"}


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
        pass

    @property
    @abc.abstractmethod
    def abi_type(self) -> ABIType:
        """
        Returns the ABI type of a Vyper type
        """
        pass

    @property
    def storage_size_in_words(self) -> int:
        # consider renaming if other word-addressable address spaces are
        # added to EVM or exist in other arches
        """
        Returns the number of words required to allocate in storage for this type
        """
        r = self.memory_bytes_required
        if r % 32 != 0:
            raise CompilerPanic("Memory bytes must be multiple of 32")
        return r // 32


# helper functions for handling old base types which are just strings
# in the future these can be reified with new type system


@dataclass
class NumericTypeInfo:
    bits: int
    is_signed: bool

    @property
    def bounds(self) -> Tuple[int, int]:
        # The bounds of this type
        # (note behavior for decimal: int value in IR land,
        # rather than Decimal value in Python land)
        return int_bounds(signed=self.is_signed, bits=self.bits)


@dataclass
class IntegerTypeInfo(NumericTypeInfo):
    pass


@dataclass
class DecimalTypeInfo(NumericTypeInfo):
    decimals: int

    @property
    def divisor(self) -> int:
        return 10 ** self.decimals

    @property
    def epsilon(self) -> Decimal:
        return 1 / Decimal(self.divisor)

    @property
    def decimal_bounds(self) -> Tuple[Decimal, Decimal]:
        lo, hi = self.bounds
        DIVISOR = Decimal(self.divisor)
        return lo / DIVISOR, hi / DIVISOR


@dataclass
class BytesMTypeInfo:
    m: int
    m_bits: int  # m_bits == m * 8, just convenient to have


_int_parser = re.compile("^(u?)int([0-9]+)$")


def is_integer_type(t: "NodeType") -> bool:
    return isinstance(t, BaseType) and _int_parser.fullmatch(t.typ) is not None


# TODO maybe move this to vyper.utils
def parse_integer_typeinfo(typename: str) -> IntegerTypeInfo:
    t = _int_parser.fullmatch(typename)
    if not t:
        raise InvalidType(f"Invalid integer type {typename}")  # pragma: notest

    return IntegerTypeInfo(is_signed=t.group(1) != "u", bits=int(t.group(2)))


def is_bytes_m_type(t: "NodeType") -> bool:
    return isinstance(t, BaseType) and t.typ.startswith("bytes")


def parse_bytes_m_info(typename: str) -> BytesMTypeInfo:
    m = int(typename[len("bytes") :])
    return BytesMTypeInfo(m=m, m_bits=m * 8)


def is_decimal_type(t: "NodeType") -> bool:
    return isinstance(t, BaseType) and t.typ == "decimal"


def parse_decimal_info(typename: str) -> DecimalTypeInfo:
    # in the future, this will actually do parsing
    assert typename == "decimal"
    return DecimalTypeInfo(bits=168, decimals=10, is_signed=True)


def is_enum_type(t: "NodeType") -> bool:
    return isinstance(t, EnumType)


def _basetype_to_abi_type(t: "BaseType") -> ABIType:
    if is_integer_type(t):
        info = t._int_info
        return ABI_GIntM(info.bits, info.is_signed)
    if is_decimal_type(t):
        info = t._decimal_info
        return ABI_FixedMxN(info.bits, info.decimals, signed=True)
    if is_bytes_m_type(t):
        return ABI_BytesM(t._bytes_info.m)
    if t.typ == "address":
        return ABI_Address()
    if t.typ == "bool":
        return ABI_Bool()

    raise InvalidType(f"Unrecognized type {t}")  # pragma: notest


# A type that represents a 1 word (32-byte) object
class BaseType(NodeType):
    def __init__(self, typename, is_literal=False):
        self.typ = typename  # e.g. "uint256"
        # TODO remove is_literal,
        # change to property on IRnode: `isinstance(self.value, int)`
        self.is_literal = is_literal

        if is_integer_type(self):
            self._int_info = parse_integer_typeinfo(typename)
            self._num_info = self._int_info
        if is_base_type(self, "address"):
            self._int_info = IntegerTypeInfo(bits=160, is_signed=False)
            self._num_info = self._int_info
        # don't generate _int_info for bool,
        # it doesn't really behave like an int in conversions
        # and should have special handling in the codebase
        if is_bytes_m_type(self):
            self._bytes_info = parse_bytes_m_info(typename)
        if is_decimal_type(self):
            self._decimal_info = parse_decimal_info(typename)
            self._num_info = self._decimal_info

    def eq(self, other):
        return self.typ == other.typ

    def __repr__(self):
        return str(self.typ)

    @property
    def abi_type(self):
        return _basetype_to_abi_type(self)

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


class EnumType(BaseType):
    def __init__(self, name, members):
        super().__init__("uint256")
        self.name = name
        self.members = members

    def __repr__(self):
        return f"enum {self.name}"

    def __eq__(self, other):
        if type(self) is not type(other):
            return False
        return self.name == other.name and self.members == other.members

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

    @property
    def abi_type(self):
        return ABI_String(self.maxlen)


# Data structure for a byte array
class ByteArrayType(ByteArrayLike):
    def __repr__(self):
        return f"Bytes[{self.maxlen}]"

    @property
    def abi_type(self):
        return ABI_Bytes(self.maxlen)


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

    @property
    def abi_type(self):
        return ABI_StaticArray(self.subtype.abi_type, self.count)


# Data structure for a dynamic array
class DArrayType(ArrayLike):
    def __repr__(self):
        return f"DynArray[{self.subtype}, {self.count}]"

    @property
    def memory_bytes_required(self):
        return DYNAMIC_ARRAY_OVERHEAD * 32 + self.count * self.subtype.memory_bytes_required

    @property
    def abi_type(self):
        return ABI_DynamicArray(self.subtype.abi_type, self.count)


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

    @property
    def abi_type(self):
        raise InvalidType("Maps are not ABI encodable")


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

    @property
    def abi_type(self):
        return ABI_Tuple([t.abi_type for t in self.tuple_members()])


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


def make_struct_type(name, sigs, members, custom_structs, enums):
    o = OrderedDict()

    for key, value in members:
        if not isinstance(key, vy_ast.Name):
            raise InvalidType(f"Invalid member variable for struct {key.id}, expected a name.", key)
        o[key.id] = parse_type(value, sigs=sigs, custom_structs=custom_structs, enums=enums)

    return StructType(o, name)


# Parses an expression representing a type.
# TODO: rename me to "ir_type_from_annotation"
def parse_type(item, sigs, custom_structs, enums):
    # sigs: set of interface or contract names in scope
    # custom_structs: struct definitions in scope
    def _sanity_check(x):
        assert x, "typechecker missed this"

    def _parse_type(item):
        return parse_type(item, sigs, custom_structs, enums)

    def FAIL():
        raise InvalidType(f"{item.id}", item)

    # Base and custom types, e.g. num
    if isinstance(item, vy_ast.Name):
        if item.id in BASE_TYPES:
            return BaseType(item.id)

        elif item.id in sigs:
            return InterfaceType(item.id)

        elif item.id in enums:
            return EnumType(item.id, enums[item.id].members.copy())

        elif item.id in custom_structs:
            return make_struct_type(item.id, sigs, custom_structs[item.id], custom_structs, enums)

        else:
            FAIL()  # pragma: notest

    # Units, e.g. num (1/sec) or contracts
    elif isinstance(item, vy_ast.Call) and isinstance(item.func, vy_ast.Name):
        # Contract_types
        if item.func.id == "address":
            if sigs and item.args[0].id in sigs:
                return InterfaceType(item.args[0].id)
        # Struct types
        elif item.func.id in custom_structs:
            return make_struct_type(item.id, sigs, custom_structs[item.id], custom_structs, enums)

        elif item.func.id == "immutable":
            if len(item.args) != 1:
                # is checked earlier but just for sanity, verify
                # immutable call is given only one argument
                raise ArgumentException("Invalid number of arguments to `immutable`", item)
            return BaseType(item.args[0].id)

        else:
            FAIL()  # pragma: notest

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
                value_type = _parse_type(item.value)
                return SArrayType(value_type, length)

        elif item.value.id == "DynArray":

            _sanity_check(isinstance(item.slice.value, vy_ast.Tuple))
            length = item.slice.value.elements[1].n
            _sanity_check(isinstance(length, int) and length > 0)

            value_type_annotation = item.slice.value.elements[0]
            value_type = _parse_type(value_type_annotation)

            return DArrayType(value_type, length)

        elif item.value.id in ("HashMap",) and isinstance(item.slice.value, vy_ast.Tuple):
            # Mappings, e.g. HashMap[address, uint256]
            key_type = _parse_type(item.slice.value.elements[0])
            value_type = _parse_type(item.slice.value.elements[1])
            return MappingType(key_type, value_type)

        else:
            FAIL()

    elif isinstance(item, vy_ast.Tuple):
        member_types = [_parse_type(t) for t in item.elements]
        return TupleType(member_types)

    else:
        FAIL()


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


# Is a type representing a number?
def is_numeric_type(typ):
    # NOTE: not quite the same as hasattr(typ, "_num_info") (address has _num_info)
    return is_integer_type(typ) or is_decimal_type(typ)


# Is a type representing some particular base type?
def is_base_type(typ, btypes):
    if not isinstance(btypes, tuple):
        btypes = (btypes,)
    return isinstance(typ, BaseType) and typ.typ in btypes
