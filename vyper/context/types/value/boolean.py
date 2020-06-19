from typing import Union

from vyper import ast as vy_ast
from vyper.context.types.bases import BasePureType, ValueTypeDefinition
from vyper.exceptions import InvalidLiteral


class BoolDefinition(ValueTypeDefinition):
    _id = "bool"

    def validate_boolean_op(self, node: vy_ast.BoolOp):
        return

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]):
        if isinstance(node.op, vy_ast.Not):
            return
        super().validate_numeric_op(node)


class BoolPureType(BasePureType):

    _id = "bool"
    _type = BoolDefinition
    _as_array = True
    _valid_literal = vy_ast.NameConstant

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        obj = super().from_literal(node)
        if node.value is None:
            raise InvalidLiteral("Invalid literal for type 'bool'", node)
        return obj
