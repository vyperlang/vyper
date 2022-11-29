from typing import Any, Dict, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_DynamicArray, ABI_StaticArray, ABI_Tuple, ABIType
from vyper.exceptions import ArrayIndexException, InvalidType, StructureException
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.primitives import UINT256_T, IntegerT
from vyper.semantics.types.utils import get_index_value, type_from_annotation


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

    # keep LGTM linter happy
    def __eq__(self, other):
        return super().__eq__(other)

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
    _id = "HashMap"

    _equality_attrs = ("key_type", "value_type")

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
    def from_annotation(cls, node: Union[vy_ast.Name, vy_ast.Call, vy_ast.Subscript]) -> "HashMapT":
        if (
            not isinstance(node, vy_ast.Subscript)
            or not isinstance(node.slice, vy_ast.Index)
            or not isinstance(node.slice.value, vy_ast.Tuple)
            or len(node.slice.value.elements) != 2
        ):
            raise StructureException(
                (
                    "HashMap must be defined with a key type and a value type, "
                    "e.g. my_hashmap: HashMap[k, v]"
                ),
                node,
            )
        # if location != DataLocation.STORAGE or is_immutable:
        #    raise StructureException("HashMap can only be declared as a storage variable", node)

        key_type = type_from_annotation(node.slice.value.elements[0])
        value_type = type_from_annotation(node.slice.value.elements[1])

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

    # keep LGTM linter happy
    def __eq__(self, other):
        return super().__eq__(other)

    def __init__(self, value_type: VyperType, length: int):

        if not 0 < length < 2 ** 256:
            raise InvalidType("Array length is invalid")

        super().__init__(UINT256_T, value_type)
        self.length = length

    def validate_index_type(self, node):
        # TODO break this cycle
        from vyper.semantics.analysis.utils import validate_expected_type

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
        if not isinstance(node, vy_ast.Subscript) or not isinstance(node.slice, vy_ast.Index):
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

    _valid_literal = (vy_ast.List,)
    _as_array = True
    _id = "DynArray"

    def __init__(self, value_type: VyperType, length: int) -> None:
        super().__init__(value_type, length)

        from vyper.semantics.types.function import MemberFunctionT

        self.add_member(
            "append",
            MemberFunctionT(self, "append", [self.value_type], None, True),
            skip_namespace_validation=True,
        )
        self.add_member(
            "pop",
            MemberFunctionT(self, "pop", [], self.value_type, True),
            skip_namespace_validation=True,
        )

    def __repr__(self):
        return f"DynArray[{self.value_type}, {self.length}]"

    @property
    def abi_type(self) -> ABIType:
        return ABI_DynamicArray(self.value_type.abi_type, self.length)

    def to_abi_arg(self, name: str = "") -> Dict[str, Any]:
        ret = self.value_type.to_abi_arg()
        # modify the child name in place.
        ret["type"] += "[]"
        return _set_first_key(ret, "name", name)

    @property
    def is_dynamic_size(self):
        return True

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
        if (
            not isinstance(node, vy_ast.Subscript)
            or not isinstance(node.slice, vy_ast.Index)
            or not isinstance(node.slice.value, vy_ast.Tuple)
            or not isinstance(node.slice.value.elements[1], vy_ast.Int)
            or len(node.slice.value.elements) != 2
        ):
            raise StructureException(
                "DynArray must be defined with base type and max length, e.g. DynArray[bool, 5]",
                node,
            )

        value_type = type_from_annotation(node.slice.value.elements[0])

        max_length = node.slice.value.elements[1].value
        return cls(value_type, max_length)


# maybe this shouldn't inherit from SequenceT. it is more like a struct.
class TupleT(_SequenceT):
    """
    Tuple type definition.

    This class is used to represent multiple return values from
    functions.
    """

    _equality_attrs = ("value_type",)

    # keep LGTM linter happy
    def __eq__(self, other):
        return super().__eq__(other)

    def __init__(self, value_type: Tuple[VyperType, ...]) -> None:
        # TODO: fix the typing here.
        super().__init__(value_type, len(value_type))  # type: ignore

        # fixes mypy error, TODO revisit typing on value_type
        self._member_types = value_type

    def __repr__(self):
        return "(" + ", ".join(repr(t) for t in self.value_type) + ")"

    @classmethod
    def from_annotation(cls, node: vy_ast.Tuple) -> VyperType:
        values = node.elements
        types = tuple(type_from_annotation(v) for v in values)
        return cls(types)

    @property
    def is_dynamic_size(self):
        return any(t.is_dynamic_size for t in self.value_type)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Tuple([t.abi_type for t in self._member_types])

    def to_abi_arg(self, name: str = "") -> dict:
        components = [t.to_abi_arg() for t in self._member_types]
        return {"name": name, "type": "tuple", "components": components}

    @property
    def size_in_bytes(self):
        return sum(i.size_in_bytes for i in self.value_type)

    def validate_index_type(self, node):
        if not isinstance(node, vy_ast.Int):
            raise InvalidType("Tuple indexes must be literals", node)
        if node.value < 0:
            raise ArrayIndexException("Vyper does not support negative indexing", node)
        if node.value >= self.length:
            raise ArrayIndexException("Index out of range", node)

    def get_subscripted_type(self, node):
        return self.value_type[node.value]

    def compare_type(self, other):
        if not isinstance(self, type(other)):
            return False
        if self.length != other.length:
            return False
        return all(self.value_type[i].compare_type(other.value_type[i]) for i in range(self.length))
