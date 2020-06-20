from typing import Tuple

from vyper import ast as vy_ast
from vyper.context.types.abstract import IntegerAbstractType
from vyper.context.types.bases import (
    BaseTypeDefinition,
    IndexableTypeDefinition,
)
from vyper.exceptions import ArrayIndexException, InvalidType


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
        is_constant: bool = False,
        is_public: bool = False,
    ) -> None:
        super().__init__(value_type, IntegerAbstractType(), _id)  # type: ignore
        self.length = length


class ArrayDefinition(_SequenceDefinition):
    """
    Array type definition.

    This class has no corresponding pure type. It is initialized
    during `context.types.utils.get_type_from_annotation`
    """

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        length: int,
        is_constant: bool = False,
        is_public: bool = False,
    ) -> None:
        super().__init__(value_type, length, f"{value_type}[{length}]", is_constant, is_public)

    def __repr__(self):
        return f"{self.value_type}[{self.length}]"

    def get_index_type(self, node):
        if isinstance(node, vy_ast.Int):
            if node.value < 0:
                raise ArrayIndexException("Vyper does not support negative indexing", node)
            if node.value < 0 or node.value >= self.length:
                raise ArrayIndexException("Index out of range", node)
        return self.value_type

    def compare_type(self, other):
        if not isinstance(self, type(other)):
            return False
        if self.length != other.length:
            return False
        return self.value_type.compare_type(other.value_type)


class TupleDefinition(_SequenceDefinition):
    """
    Tuple type definition.

    This class has no corresponding pure type. It is used to represent
    multiple return values from `types.function.ContractFunctionType`.
    """

    def __init__(self, value_type: Tuple[BaseTypeDefinition, ...]) -> None:
        super().__init__(
            value_type, len(value_type), f"{value_type}", is_constant=True  # type: ignore
        )

    def __repr__(self):
        return self._id

    def get_index_type(self, node):
        if not isinstance(node, vy_ast.Int):
            raise InvalidType("Tuple indexes must be literals", node)
        if node.value < 0:
            raise ArrayIndexException("Vyper does not support negative indexing", node)
        if node.value < 0 or node.value >= self.length:
            raise ArrayIndexException("Index out of range", node)
        return self.value_type[node.value]

    def compare_type(self, other):
        if not isinstance(self, type(other)):
            return False
        if self.length != other.length:
            return False
        return all(self.value_type[i].compare_type(other.value_type[i]) for i in range(self.length))
