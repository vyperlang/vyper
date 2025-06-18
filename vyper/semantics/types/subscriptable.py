from typing import Any, Dict, Optional, Tuple

from vyper import ast as vy_ast
from vyper.abi_types import ABI_DynamicArray, ABI_StaticArray, ABI_Tuple, ABIType
from vyper.exceptions import ArrayIndexException, InvalidType, StructureException
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.primitives import IntegerT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.utils import get_index_value, type_from_annotation
from vyper.warnings import VyperWarning, vyper_warn


class _SubscriptableT(VyperType):
    """
    Base class for subscriptable types such as arrays and mappings.

    Attributes
    ----------
    key_type: VyperType
        Type representing the index for this object.
    value_type : VyperType
        Type representing the value(s) contained in this object.
    """

    def __init__(self, key_type: VyperType, value_type: VyperType) -> None:
        super().__init__()
        self.key_type = key_type
        self.value_type = value_type

    @property
    def getter_signature(self) -> Tuple[Tuple, Optional[VyperType]]:
        child_keys, return_type = self.value_type.getter_signature
        return (self.key_type,) + child_keys, return_type

    def validate_index_type(self, node):
        # TODO: break this cycle
        from vyper.semantics.analysis.utils import validate_expected_type

        validate_expected_type(node, self.key_type)


class HashMapT(_SubscriptableT):
    typeclass = "hashmap"
    _id = "HashMap"  # CMC 2024-03-03 maybe this would be better as repr(self)

    _equality_attrs = ("key_type", "value_type")

    # disallow everything but storage or transient
    _invalid_locations = (
        DataLocation.UNSET,
        DataLocation.CALLDATA,
        DataLocation.CODE,
        DataLocation.MEMORY,
    )

    def __repr__(self):
        return f"HashMap[{self.key_type}, {self.value_type}]"

    # TODO not sure this is used?
    def compare_type(self, other):
        return (
            super().compare_type(other)
            and self.key_type == other.key_type
            and self.value_type == other.value_type
        )

    def get_subscripted_type(self, node):
        return self.value_type

    @classmethod
    def from_annotation(cls, node: vy_ast.Subscript) -> "HashMapT":
        if (
            not isinstance(node, vy_ast.Subscript)
            or not isinstance(node.slice, vy_ast.Tuple)
            or len(node.slice.elements) != 2
        ):
            raise StructureException(
                (
                    "HashMap must be defined with a key type and a value type, "
                    "e.g. my_hashmap: HashMap[k, v]"
                ),
                node,
            )

        k_ast, v_ast = node.slice.elements
        key_type = type_from_annotation(k_ast)
        if not key_type._as_hashmap_key:
            raise InvalidType("can only use primitive types as HashMap key!", k_ast)

        # TODO: thread through actual location - might also be TRANSIENT
        value_type = type_from_annotation(v_ast, DataLocation.STORAGE)

        return cls(key_type, value_type)


class _SequenceT(_SubscriptableT):
    """
    Private base class for sequence types (i.e., index is an int)

    Arguments
    ---------
    length : int
        Number of items in the type.
    """

    _equality_attrs: tuple = ("value_type", "length")

    _is_array_type: bool = True

    def __init__(self, value_type: VyperType, length: int):
        if not 0 < length < 2**256:
            raise InvalidType("Array length is invalid")

        if length >= 2**64:
            vyper_warn(VyperWarning("Use of large arrays can be unsafe!"))

        super().__init__(UINT256_T, value_type)
        self.length = length

    @property
    def count(self):
        """
        Alias for API compatibility
        """
        return self.length

    def validate_index_type(self, node):
        # TODO break this cycle
        from vyper.semantics.analysis.utils import validate_expected_type

        node = node.reduced()

        if isinstance(node, vy_ast.Int):
            if node.value < 0:
                raise ArrayIndexException("Vyper does not support negative indexing", node)
            if node.value >= self.length:
                raise ArrayIndexException("Index out of range", node)

        validate_expected_type(node, IntegerT.any())

    def get_subscripted_type(self, node):
        return self.value_type


# override value at `k` with `val`, but inserting it before other keys
# for formatting reasons. besides insertion order, equivalent to
# `{k: val, **xs}`
def _set_first_key(xs: Dict[str, Any], k: str, val: Any) -> dict:
    xs.pop(k, None)
    return {k: val, **xs}


class SArrayT(_SequenceT):
    """
    Static array type
    """

    typeclass = "static_array"

    _id = "$SArray"

    def __init__(self, value_type: VyperType, length: int) -> None:
        super().__init__(value_type, length)

    def __repr__(self):
        return f"{self.value_type}[{self.length}]"

    @property
    def _as_array(self):
        # a static array is arrayable if its value_type is arrayble.
        return self.value_type._as_array

    @property
    def abi_type(self) -> ABIType:
        return ABI_StaticArray(self.value_type.abi_type, self.length)

    def to_abi_arg(self, name: str = "") -> Dict[str, Any]:
        ret = self.value_type.to_abi_arg()
        # modify the child name in place
        ret["type"] += f"[{self.length}]"
        return _set_first_key(ret, "name", name)

    # TODO rename to `memory_bytes_required`
    @property
    def size_in_bytes(self):
        return self.value_type.size_in_bytes * self.length

    @property
    def subtype(self):
        """
        Alias for API compatibility with codegen
        """
        return self.value_type

    def get_subscripted_type(self, node):
        return self.value_type

    def compare_type(self, other):
        if not isinstance(self, type(other)):
            return False
        if self.length != other.length:
            return False
        return self.value_type.compare_type(other.value_type)

    @classmethod
    def from_annotation(cls, node: vy_ast.Subscript) -> "SArrayT":
        if not isinstance(node, vy_ast.Subscript):
            raise StructureException(
                "Arrays must be defined with base type and length, e.g. bool[5]", node
            )

        value_type = type_from_annotation(node.value)

        if not value_type._as_array:
            raise StructureException(f"arrays of {value_type} are not allowed!")

        # note: validates index is a vy_ast.Int.
        length = get_index_value(node.slice)
        return cls(value_type, length)


class DArrayT(_SequenceT):
    """
    Dynamic array type
    """

    typeclass = "dynamic_array"

    _valid_literal = (vy_ast.List,)
    _as_array = True

    _id = "DynArray"  # CMC 2024-03-03 maybe this would be better as repr(self)

    def __init__(self, value_type: VyperType, length: int) -> None:
        super().__init__(value_type, length)

        from vyper.semantics.types.function import MemberFunctionT

        self.add_member("append", MemberFunctionT(self, "append", [self.value_type], None, True))
        self.add_member("pop", MemberFunctionT(self, "pop", [], self.value_type, True))

    def __repr__(self):
        return f"DynArray[{self.value_type}, {self.length}]"

    @property
    def subtype(self):
        """
        Alias for backwards compatibility.
        """
        return self.value_type

    @property
    def count(self):
        """
        Alias for backwards compatibility.
        """
        return self.length

    @property
    def abi_type(self) -> ABIType:
        return ABI_DynamicArray(self.value_type.abi_type, self.length)

    def to_abi_arg(self, name: str = "") -> Dict[str, Any]:
        ret = self.value_type.to_abi_arg()
        # modify the child name in place.
        ret["type"] += "[]"
        return _set_first_key(ret, "name", name)

    # TODO rename me to memory_bytes_required
    @property
    def size_in_bytes(self):
        # one length word + size of the array items
        return 32 + self.value_type.size_in_bytes * self.length

    def compare_type(self, other):
        # TODO allow static array to be assigned to dyn array?
        # if not isinstance(other, (DArrayT, SArrayT)):
        if not isinstance(self, type(other)):
            return False
        if self.length < other.length:
            return False
        return self.value_type.compare_type(other.value_type)

    @classmethod
    def from_annotation(cls, node: vy_ast.Subscript) -> "DArrayT":
        # common error message, different ast locations
        err_msg = "DynArray must be defined with base type and max length, e.g. DynArray[bool, 5]"

        if not isinstance(node, vy_ast.Subscript):
            raise StructureException(err_msg, node)

        if not isinstance(node.slice, vy_ast.Tuple) or len(node.slice.elements) != 2:
            raise StructureException(err_msg, node.slice)

        length_node = node.slice.elements[1].reduced()

        if not isinstance(length_node, vy_ast.Int):
            raise StructureException(err_msg, length_node)

        length = length_node.value

        value_node = node.slice.elements[0]
        value_type = type_from_annotation(value_node)
        if not value_type._as_darray:
            raise StructureException(f"Arrays of {value_type} are not allowed", value_node)

        return cls(value_type, length)


class TupleT(VyperType):
    """
    Tuple type definition.

    This class is used to represent multiple return values from functions.
    """

    typeclass = "tuple"

    _equality_attrs = ("members",)
    _id = "$Tuple"

    # note: docs say that tuples are not instantiable but they
    # are in fact instantiable and the codegen works. if we
    # wanted to be stricter in the typechecker, we could
    # add _invalid_locations = everything but UNSET and RETURN_VALUE.
    # (we would need to add a DataLocation.RETURN_VALUE in order for
    # tuples to be instantiable as return values but not in memory).
    # _invalid_locations = ...

    def __init__(self, member_types: Tuple[VyperType, ...]) -> None:
        super().__init__()
        for mt in member_types:
            if not mt._as_tuple_member:
                raise StructureException(f"not a valid tuple member: {mt}")
        self.member_types = member_types
        self.key_type = UINT256_T  # API Compatibility

    def __repr__(self):
        if len(self.member_types) == 1:
            (t,) = self.member_types
            return f"({t},)"
        return "(" + ", ".join(f"{t}" for t in self.member_types) + ")"

    @property
    def length(self):
        return len(self.member_types)

    def tuple_members(self):
        return [v for (_k, v) in self.tuple_items()]

    def tuple_keys(self):
        return [k for (k, _v) in self.tuple_items()]

    def tuple_items(self):
        return list(enumerate(self.member_types))

    @classmethod
    def from_annotation(cls, node: vy_ast.Tuple) -> "TupleT":
        values = node.elements
        types = tuple(type_from_annotation(v) for v in values)
        return cls(types)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Tuple([t.abi_type for t in self.member_types])

    def to_abi_arg(self, name: str = "") -> dict:
        components = [t.to_abi_arg() for t in self.member_types]
        return {"name": name, "type": "tuple", "components": components}

    @property
    def size_in_bytes(self):
        return sum(i.size_in_bytes for i in self.member_types)

    def validate_index_type(self, node):
        node = node.reduced()

        if not isinstance(node, vy_ast.Int):
            raise InvalidType("Tuple indexes must be literals", node)
        if node.value < 0:
            raise ArrayIndexException("Vyper does not support negative indexing", node)
        if node.value >= self.length:
            raise ArrayIndexException("Index out of range", node)

    def get_subscripted_type(self, node):
        node = node.reduced()
        return self.member_types[node.value]

    def compare_type(self, other):
        if not isinstance(self, type(other)):
            return False
        if self.length != other.length:
            return False
        return all(a.compare_type(b) for (a, b) in zip(self.member_types, other.member_types))
