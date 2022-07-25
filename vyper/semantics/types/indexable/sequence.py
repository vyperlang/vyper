from typing import Any, Dict, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_DynamicArray, ABI_StaticArray, ABI_Tuple, ABIType
from vyper.exceptions import ArrayIndexException, InvalidType, StructureException
from vyper.semantics import validation
from vyper.semantics.types.abstract import IntegerAbstractType
from vyper.semantics.types.bases import (
    BasePrimitive,
    BaseTypeDefinition,
    DataLocation,
    IndexableTypeDefinition,
    MemberTypeDefinition,
)
from vyper.semantics.types.value.numeric import Uint256Definition  # type: ignore


class _SequenceDefinition(IndexableTypeDefinition):
    """
    Private base class for sequence types.

    Arguments
    ---------
    length : int
        Number of items in the type.
    """

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        length: int,
        _id: str,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        if not 0 < length < 2 ** 256:
            raise InvalidType("Array length is invalid")
        super().__init__(
            value_type,
            IntegerAbstractType(),  # type: ignore
            _id,
            location=location,
            is_constant=is_constant,
            is_public=is_public,
            is_immutable=is_immutable,
        )
        self.length = length

    def get_signature(self) -> Tuple[Tuple, Optional[BaseTypeDefinition]]:
        # override the default behavior to return `Uint256Definition`
        # an external interface cannot use `IntegerAbstractType` because
        # abstract types have no canonical type
        new_args, return_type = self.value_type.get_signature()
        return (Uint256Definition(),) + new_args, return_type

    def get_index_type(self) -> BaseTypeDefinition:
        # override the default behaviour to return `Uint256Definition` for
        # type annotation
        return Uint256Definition()


# override value at `k` with `val`, but inserting it before other keys
# for formatting reasons. besides insertion order, equivalent to
# `{k: val, **xs}`
def _set_first_key(xs: Dict[str, Any], k: str, val: Any) -> dict:
    xs.pop(k, None)
    return {k: val, **xs}


# TODO rename me to StaticArrayDefinition?
class ArrayDefinition(_SequenceDefinition):
    """
    Array type definition.

    This class has no corresponding primitive. It is initialized
    during `context.types.utils.get_type_from_annotation`
    """

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        length: int,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        super().__init__(
            value_type,
            length,
            f"{value_type}[{length}]",
            location,
            is_constant,
            is_public,
            is_immutable,
        )

    def __repr__(self):
        return f"{self.value_type}[{self.length}]"

    @property
    def abi_type(self) -> ABIType:
        return ABI_StaticArray(self.value_type.abi_type, self.length)

    def to_abi_dict(self, name: str = "") -> Dict[str, Any]:
        ret = self.value_type.to_abi_dict()
        # modify the child name in place
        ret["type"] += f"[{self.length}]"
        return _set_first_key(ret, "name", name)

    @property
    def is_dynamic_size(self):
        return self.value_type.is_dynamic_size

    @property
    def size_in_bytes(self):
        return self.value_type.size_in_bytes * self.length

    def validate_index_type(self, node):
        if isinstance(node, vy_ast.Int):
            if node.value < 0:
                raise ArrayIndexException("Vyper does not support negative indexing", node)
            if node.value >= self.length:
                raise ArrayIndexException("Index out of range", node)

        validation.utils.validate_expected_type(node, IntegerAbstractType())

    def get_subscripted_type(self, node):
        return self.value_type

    def compare_type(self, other):
        if not isinstance(self, type(other)):
            return False
        if self.length != other.length:
            return False
        return self.value_type.compare_type(other.value_type)


class DynamicArrayDefinition(_SequenceDefinition, MemberTypeDefinition):
    """
    Dynamic array type definition.
    """

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        length: int,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:

        super().__init__(
            value_type, length, "DynArray", location, is_constant, is_public, is_immutable
        )

        # Adding members here as otherwise MemberFunctionDefinition is not yet defined
        # if added as _type_members
        from vyper.semantics.types.function import MemberFunctionDefinition

        self.add_member(
            "append", MemberFunctionDefinition(self, "append", [self.value_type], None, True)
        )
        self.add_member("pop", MemberFunctionDefinition(self, "pop", [], self.value_type, True))

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

    def validate_index_type(self, node):
        if isinstance(node, vy_ast.Int):
            if node.value < 0:
                raise ArrayIndexException("Vyper does not support negative indexing", node)
            if node.value >= self.length:
                raise ArrayIndexException("Index out of range", node)
        else:
            validation.utils.validate_expected_type(node, IntegerAbstractType())

    def get_subscripted_type(self, node):
        return self.value_type

    def compare_type(self, other):
        # TODO allow static array to be assigned to dyn array?
        # if not isinstance(other, (DynamicArrayDefinition, ArrayDefinition)):
        if not isinstance(self, type(other)):
            return False
        if self.length < other.length:
            return False
        return self.value_type.compare_type(other.value_type)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        pass


class DynamicArrayPrimitive(BasePrimitive):
    _id = "DynArray"
    _type = DynamicArrayDefinition
    _valid_literal = (vy_ast.List,)
    _as_array = True

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call, vy_ast.Subscript],
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> DynamicArrayDefinition:
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
        return DynamicArrayDefinition(
            value_type, max_length, location, is_constant, is_public, is_immutable
        )


class TupleDefinition(_SequenceDefinition):
    """
    Tuple type definition.

    This class has no corresponding primitive. It is used to represent
    multiple return values from `types.function.ContractFunction`.
    """

    def __init__(self, value_type: Tuple[BaseTypeDefinition, ...]) -> None:
        # always use the most restrictive location re: modification
        location = sorted((i.location for i in value_type), key=lambda k: k.value)[-1]
        is_constant = any((getattr(i, "is_constant", False) for i in value_type))
        super().__init__(
            # TODO fix the typing on value_type
            value_type,  # type: ignore
            len(value_type),
            f"{value_type}",
            location,
            is_constant,
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
