from typing import Optional, Tuple, Type, Union

from vyper import ast as vy_ast
from vyper.context.types.abstract import FixedAbstractType, IntegerAbstractType
from vyper.context.types.bases import (
    BasePrimitive,
    BaseTypeDefinition,
    ValueTypeDefinition,
)
from vyper.exceptions import InvalidOperation, OverflowException


class _NumericDefinition(ValueTypeDefinition):
    """
    Private base class for numeric definitions.

    Attributes
    ----------
    _invalid_op : VyperNode, optional
        Vyper ast node, or list of nodes, that is not a valid operator for binary
        operations on this type.
    """

    _invalid_op: Optional[Type[vy_ast.VyperNode]] = None

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if self._invalid_op and isinstance(node.op, self._invalid_op):
            raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        # all comparators are valid on numeric types
        return


class _NumericPrimitive(BasePrimitive):

    _as_array = True
    _bounds: Tuple[int, int]

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> BaseTypeDefinition:
        obj = super().from_literal(node)
        lower, upper = cls._bounds
        if node.value < lower:
            raise OverflowException(f"Value is below lower bound for given type ({lower})", node)
        if node.value > upper:
            raise OverflowException(f"Value exceeds upper bound for given type ({upper})", node)
        return obj


# definitions


class Int128Definition(IntegerAbstractType, _NumericDefinition):
    _id = "int128"


class Uint256Definition(IntegerAbstractType, _NumericDefinition):
    _id = "uint256"
    _invalid_op = vy_ast.USub


class DecimalDefinition(FixedAbstractType, _NumericDefinition):
    _id = "decimal"
    _invalid_op = vy_ast.Pow


# primitives


class Int128Primitive(_NumericPrimitive):
    _bounds = (-(2 ** 127), 2 ** 127 - 1)
    _id = "int128"
    _type = Int128Definition
    _valid_literal = (vy_ast.Int,)


class Uint256Primitive(_NumericPrimitive):
    _bounds = (0, 2 ** 256 - 1)
    _id = "uint256"
    _type = Uint256Definition
    _valid_literal = (vy_ast.Int,)


class DecimalPrimitive(_NumericPrimitive):
    _bounds = (-(2 ** 127), 2 ** 127 - 1)
    _id = "decimal"
    _type = DecimalDefinition
    _valid_literal = (vy_ast.Decimal,)
