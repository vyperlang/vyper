from typing import Union

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.types.bases import BasePrimitive, IndexableTypeDefinition
from vyper.context.types.utils import get_type_from_annotation
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import CompilerPanic


class MappingDefinition(IndexableTypeDefinition):
    _id = "map"

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
    _id = "map"
    _valid_literal = ()

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call],
        is_constant: bool = False,
        is_public: bool = False,
    ) -> MappingDefinition:
        if isinstance(node, vy_ast.Name):
            raise CompilerPanic("Node must be a call")

        validate_call_args(node, 2)
        key_type = get_type_from_annotation(node.args[0])
        value_type = get_type_from_annotation(node.args[1])
        return MappingDefinition(
            value_type, key_type, f"map({key_type}, {value_type})", is_constant, is_public,
        )
