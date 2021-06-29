from typing import Union

from vyper import ast as vy_ast
from vyper.exceptions import InvalidLiteral

from ..bases import BasePrimitive, BaseTypeDefinition, ValueTypeDefinition


class BoolDefinition(ValueTypeDefinition):
    _id = "bool"

    def validate_boolean_op(self, node: vy_ast.BoolOp) -> None:
        return

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        if isinstance(node.op, vy_ast.Not):
            return
        super().validate_numeric_op(node)


class BoolPrimitive(BasePrimitive):

    _as_array = True
    _id = "bool"
    _type = BoolDefinition
    _valid_literal = (vy_ast.NameConstant,)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> BaseTypeDefinition:
        obj = super().from_literal(node)
        if node.value is None:
            raise InvalidLiteral("Invalid literal for type 'bool'", node)
        return obj
