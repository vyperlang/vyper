from typing import Union

from vyper import ast as vy_ast
from vyper.context.types.bases import AbstractDataType, BasePureType
from vyper.context.types.value.bases import ValueType
from vyper.exceptions import InvalidOperation, InvalidType, OverflowException

# abstract data types


class NumericBase(AbstractDataType):
    """
    Abstract data class for numeric types (capable of arithmetic).

    Attributes
    ----------
    _invalid_op : VyperNode, optional
        Vyper ast node, or list of nodes, that is not a valid operator for binary
        operations on this type.
    """

    _invalid_op = None

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]) -> None:
        if self._invalid_op and isinstance(node.op, self._invalid_op):
            raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        # all comparators are valid on numeric types
        return


class IntegerBase(NumericBase):
    """Abstract data class for integer numeric types (int128, uint256)."""


class FixedBase(NumericBase):
    """
    Abstract data class for decimal numeric types.

    Note that Vyper currently only has one decimal type - this class should
    still be used to expect decimal values in anticipation of multiple decimal
    types in a future release.
    """


# castable types


class Int128Type(IntegerBase, ValueType):
    _id = "int128"


class Uint256Type(IntegerBase, ValueType):
    _id = "uint256"
    _invalid_op = vy_ast.USub


class DecimalType(FixedBase, ValueType):
    _id = "decimal"
    _invalid_op = vy_ast.Pow


# pure types


class Int128Pure(BasePureType):

    _as_array = True
    _type = Int128Type
    _id = "int128"
    _valid_literal = vy_ast.Int

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        super().from_literal(node)
        validate_numeric_bounds("int128", node)
        return Int128Type()


class Uint256Pure(BasePureType):
    _type = Uint256Type
    _id = "uint256"
    _as_array = True
    _valid_literal = vy_ast.Int

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        obj = super().from_literal(node)
        validate_numeric_bounds("uint256", node)
        return obj


class DecimalPure(BasePureType):
    _as_array = True
    _type = DecimalType
    _id = "decimal"
    _valid_literal = vy_ast.Decimal

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        obj = super().from_literal(node)
        validate_numeric_bounds("int128", node)
        return obj


def validate_numeric_bounds(type_str: str, node: vy_ast.Num) -> None:
    """
    Validate that a `Num` node's value is within the bounds of a given type.

    Raises `OverflowException` if the check fails.

    Arguments
    ---------
    type_str : str
        String representation of the type, e.g. "int128"
    node : Num
        Vyper ast node to validate

    Returns
    -------
    None
    """
    size = int(type_str.strip("uint") or 256)
    if not 8 <= size <= 256 or size % 8:
        raise InvalidType(f"Invalid type: {type_str}")
    if type_str.startswith("u"):
        lower, upper = 0, 2 ** size - 1
    else:
        lower, upper = -(2 ** (size - 1)), 2 ** (size - 1) - 1

    value = node.value
    if value < lower:
        raise OverflowException(f"Value is below lower bound for given type ({lower})", node)
    if value > upper:
        raise OverflowException(f"Value exceeds upper bound for given type ({upper})", node)
