from typing import Optional, Tuple, Type, Union

from vyper import ast as vy_ast
from vyper.context.types.abstract import FixedAbstractType, IntegerAbstractType
from vyper.context.types.bases import (
    BasePrimitive,
    BaseTypeDefinition,
    CompilerPanic,
    ValueTypeDefinition,
)
from vyper.exceptions import InvalidOperation, OverflowException


class _NumericDefinition(ValueTypeDefinition):
    """
    Private base class for numeric definitions.

    Attributes
    ----------
    _bits : int
        Number of bits the value occupies in memory
    _is_signed : bool
        Is the value signed?
    _invalid_op : VyperNode, optional
        Vyper ast node, or list of nodes, that is not a valid operator for binary
        operations on this type.
    """

    _invalid_op: Optional[Type[vy_ast.VyperNode]] = None
    _bits: int
    _is_signed: bool

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if self._invalid_op and isinstance(node.op, self._invalid_op):
            raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

        if isinstance(node.op, vy_ast.Pow):
            if isinstance(node, vy_ast.BinOp):
                left, right = node.left, node.right
            elif isinstance(node, vy_ast.AugAssign):
                left, right = node.target, node.value
            else:
                raise CompilerPanic(f"Unexpected node type for numeric op: {type(node).__name__}")

            value_bits = self._bits - (1 if self._is_signed else 0)

            # constant folding ensures one of `(left, right)` is never a literal
            if isinstance(left, vy_ast.Int):
                if left.value >= 2 ** value_bits:
                    raise OverflowException(
                        "Base is too large, calculation will always overflow", left
                    )
                elif left.value < -(2 ** value_bits):
                    raise OverflowException(
                        "Base is too small, calculation will always underflow", left
                    )
            elif isinstance(right, vy_ast.Int):
                if right.value < 0:
                    raise InvalidOperation("Cannot calculate a negative power", right)
                if right.value > value_bits:
                    raise OverflowException(
                        "Power is too large, calculation will always overflow", right
                    )
            else:
                msg = (
                    "Cannot apply an overflow check on exponentiation when both "
                    "the base and power are unknown at compile-time."
                )
                if not self._is_signed:
                    msg = (
                        f"{msg} To perform this operation without an overflow check, use "
                        f"`pow_mod256({left.node_source_code}, {right.node_source_code})`"
                    )
                raise InvalidOperation(msg, node)

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        # all comparators are valid on numeric types
        return


class _SignedIntegerDefinition(_NumericDefinition):
    """
    Private base class for signed integer definitions.
    """

    _is_signed = True

    @property
    def _id(self):
        return f"int{self._bits}"


class _UnsignedIntegerDefinition(_NumericDefinition):
    """
    Private base class for unsigned integer definitions.
    """

    _is_signed = False

    @property
    def _id(self):
        return f"uint{self._bits}"


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


class Int128Definition(IntegerAbstractType, _SignedIntegerDefinition):
    _bits = 128


class Uint256Definition(IntegerAbstractType, _UnsignedIntegerDefinition):
    _bits = 256
    _invalid_op = vy_ast.USub


class DecimalDefinition(FixedAbstractType, _NumericDefinition):
    _bits = 168
    _id = "decimal"
    _is_signed = True
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
