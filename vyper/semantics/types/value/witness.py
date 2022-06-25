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


class WitnessDefinition(MemberTypeDefinition):
    """
    Dynamic array type definition.
    """
    _id = "Witness"

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        self.value_type = value_type

        super().__init__(
            location, is_constant, is_public, is_immutable
        )

        # Adding members here as otherwise MemberFunctionDefinition is not yet defined
        # if added as _type_members
        from vyper.semantics.types.function import MemberFunctionDefinition

        self.add_member(
            "validate", MemberFunctionDefinition(self, "validate", [ProofDefinition(self.value_type)], self.value_type, True)
        )

    def __repr__(self):
        return f"Witness[{self.value_type}]"

    @property
    def abi_type(self) -> ABIType:
        return ABI_BytesM(32)

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


class WitnessPrimitive(BasePrimitive):
    _id = "Witness"
    _type = WitnessDefinition
    _valid_literal = (vy_ast.List,)

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call, vy_ast.Subscript],
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> WitnessDefinition:
        # TODO fix circular import
        from vyper.semantics.types.utils import get_type_from_annotation

        if (
            not isinstance(node, vy_ast.Subscript)
            or not isinstance(node.slice, vy_ast.Index)
        ):
            raise StructureException("Witness must be good", node)

        value_type = get_type_from_annotation(
            node.slice.value, location, is_constant, is_public, is_immutable
        )

        return WitnessDefinition(
            value_type, location, is_constant, is_public, is_immutable
        )


class ProofDefinition(MemberTypeDefinition):
    """
    Dynamic array type definition.
    """

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        self.value_type = value_type

        super().__init__(
            location, is_constant, is_public, is_immutable
        )


    def __repr__(self):
        return f"Proof[{self.value_type}]"

    @property
    def abi_type(self) -> ABIType:
        return self.value_type.abi_type

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
        return self.value_type.compare_type(other.value_type)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        pass


class ProofPrimitive(BasePrimitive):
    _id = "Proof"
    _type = ProofDefinition
    _valid_literal = (vy_ast.List,)

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call, vy_ast.Subscript],
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> ProofDefinition:
        # TODO fix circular import
        from vyper.semantics.types.utils import get_type_from_annotation

        if (
            not isinstance(node, vy_ast.Subscript)
            or not isinstance(node.slice, vy_ast.Index)
        ):
            raise StructureException("Proof must be good", node)

        value_type = get_type_from_annotation(
            node.slice.value, location, is_constant, is_public, is_immutable
        )

        return ProofDefinition(
            value_type, location, is_constant, is_public, is_immutable
        )
