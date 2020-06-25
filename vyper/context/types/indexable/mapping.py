from typing import Union

from vyper import ast as vy_ast
from vyper.context.types.bases import (
    BasePrimitive,
    DataLocation,
    IndexableTypeDefinition,
)
from vyper.context.types.utils import get_type_from_annotation
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import CompilerPanic, StructureException


class MappingDefinition(IndexableTypeDefinition):
    _id = "HashMap"

    def compare_type(self, other):
        return (
            super().compare_type(other)
            and self.key_type == other.key_type
            and self.value_type == other.value_type
        )

    def get_index_type(self, node):
        validate_expected_type(node, self.key_type)
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
    ) -> MappingDefinition:
        if not isinstance(node, vy_ast.Subscript):
            raise CompilerPanic("Node must be a subscript")
        if not isinstance(node.slice.value, vy_ast.Tuple):
            raise CompilerPanic("Mapping must be a subscript with a Tuple Index")
        if location != DataLocation.STORAGE:
            raise StructureException("Mapping can only be declared as a storage variable", node)

        if len(node.slice.value.elements) != 2:
            raise StructureException("Mapping must have two args: key type, and value type", node)
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
