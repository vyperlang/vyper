from typing import Any, Dict, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_DynamicArray, ABI_StaticArray, ABI_Tuple, ABIType
from vyper.exceptions import ArrayIndexException, InvalidType, StructureException
from vyper.semantics.types.base import DataLocation, VyperType
from vyper.semantics.types.primitives import UINT256_T, IntegerT
from vyper.semantics.types.utils import type_from_annotation
from vyper.utils import cached_property


class _SubscriptableT(VyperType):
    """
    Base class for subscriptable types such as arrays and mappings.

    Attributes
    ----------
    key_type: VyperType
        Type representing the index for this object.
    value_type : VyperType
        Type representing the value(s) contained in this object.
    _id : str
        Name of the type.
    """

    def __init__(self, key_type: VyperType, value_type: VyperType) -> None:
        super().__init__()
        self.key_type = key_type
        self.value_type = value_type

    def getter_signature(self) -> Tuple[Tuple, Optional[VyperType]]:
        child_keys, return_type = self.value_type.getter_signature()
        return (self.key_type,) + child_keys, return_type

    # TODO maybe remove this
    @cached_property
    def possible_index_types(self):
        return (self.key_type,)


class HashMapT(_SubscriptableT):
    _id = "HashMap"

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

    def __init__(self, value_type: VyperType, length: int):

        if not 0 < length < 2 ** 256:
            raise InvalidType("Array length is invalid")

        super().__init__(UINT256_T, value_type)
        self.length = length

    @cached_property
    def possible_index_types(self) -> Tuple[VyperType]:
        return IntegerT.any()

    def validate_index_type(self, node):
        # TODO break this cycle
        from vyper.semantics.validation.utils import validate_expected_type

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
    Array type definition.

    This class has no corresponding primitive. It is initialized
    during `context.types.utils.get_type_from_annotation`
    """

    def __init__(self, value_type: VyperType, length: int) -> None:
        super().__init__(value_type, length)

    def __repr__(self):
        return f"{self.value_type}[{self.length}]"

    @property
    def _id(self):
        return repr(self)

    @property
    def abi_type(self) -> ABIType:
        return ABI_StaticArray(self.value_type.abi_type, self.length)

    def to_abi_dict(self, name: str = "") -> Dict[str, Any]:
        ret = self.value_type.to_abi_dict()
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

    def to_abi_dict(self, name: str = "") -> Dict[str, Any]:
        ret = self.value_type.to_abi_dict()
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

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        pass

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call, vy_ast.Subscript],
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> "DArrayT":
        # TODO fix circular import
        from vyper.semantics.types.utils import get_type_from_annotation

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

        value_type = get_type_from_annotation(
            node.slice.value.elements[0], location, is_constant, is_public, is_immutable
        )

        max_length = node.slice.value.elements[1].value
        return DArrayT(value_type, max_length)


class TupleT(_SequenceT):
    """
    Tuple type definition.

    This class has no corresponding primitive. It is used to represent
    multiple return values from `types.function.ContractFunction`.
    """

    def __init__(self, value_type: Tuple[VyperType, ...]) -> None:
        # always use the most restrictive location re: modification
        # location = sorted((i.location for i in value_type), key=lambda k: k.value)[-1]
        # is_constant = any((getattr(i, "is_constant", False) for i in value_type))

        super().__init__(
            # TODO fix the typing on value_type
            value_type,  # type: ignore
            len(value_type),
        )

        # fixes mypy error, TODO revisit typing on value_type
        self._member_types = value_type

    def __repr__(self):
        return self._id

    @property
    def is_dynamic_size(self):
        return any(t.is_dynamic_size for t in self.value_type)

    @property
    def abi_type(self) -> ABIType:
        return ABI_Tuple([t.abi_type for t in self._member_types])

    def to_abi_dict(self, name: str = "") -> dict:
        components = [t.to_abi_dict() for t in self._member_types]
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
