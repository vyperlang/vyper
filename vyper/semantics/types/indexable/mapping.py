from typing import Union

from vyper import ast as vy_ast
from vyper.exceptions import StructureException
from vyper.semantics.types.bases import BasePrimitive, DataLocation, IndexableTypeDefinition
from vyper.semantics.types.utils import get_type_from_annotation
from vyper.semantics.validation.utils import validate_expected_type


class MappingDefinition(IndexableTypeDefinition):
    _id = "HashMap"

    def __repr__(self):
        return f"HashMap[{self.key_type}, {self.value_type}]"

    def compare_type(self, other):
        return (
            super().compare_type(other)
            and self.key_type == other.key_type
            and self.value_type == other.value_type
        )

    def validate_index_type(self, node):
        validate_expected_type(node, self.key_type)

    def get_subscripted_type(self, node):
        return self.value_type


class MappingPrimitive(BasePrimitive):
    _id = "HashMap"
    _valid_literal = ()

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call, vy_ast.Subscript],
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> MappingDefinition:
        if (
            not isinstance(node, vy_ast.Subscript)
            or not isinstance(node.slice, vy_ast.Index)
            or not isinstance(node.slice.value, vy_ast.Tuple)
            or len(node.slice.value.elements) != 2
        ):
            raise StructureException(
                "HashMap must be defined with a key type and a value type", node
            )
        if location != DataLocation.STORAGE or is_immutable:
            raise StructureException("HashMap can only be declared as a storage variable", node)

        key_type = get_type_from_annotation(node.slice.value.elements[0], DataLocation.UNSET)
        value_type = get_type_from_annotation(node.slice.value.elements[1], DataLocation.STORAGE)
        return MappingDefinition(
            value_type,
            key_type,
            f"HashMap[{key_type}, {value_type}]",
            location,
            is_constant,
            is_public,
        )
