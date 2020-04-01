from typing import (
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    InvalidOperation,
)


class NumericBase:

    """Base class for simple numeric types (capable of arithmetic)."""

    __slots__ = ()
    _invalid_op = None

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]) -> None:
        if self._invalid_op and isinstance(node.op, self._invalid_op):
            raise InvalidOperation(
               f"Cannot perform {node.op.description} on {self}", node
            )

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        return


class IntegerBase(NumericBase):

    """Base class for integer numeric types (int128, uint256)."""

    __slots__ = ()


class FixedBase(NumericBase):
    __slots__ = ()


class BytesBase:

    """Base class for bytes types (bytes32, bytes[])."""

    __slots__ = ()


class StringBase:
    __slots__ = ()


class BoolBase:
    __slots__ = ()


class AddressBase:
    __slots__ = ()
