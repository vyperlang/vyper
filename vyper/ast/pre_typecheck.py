from decimal import Decimal
from typing import Any

from vyper import ast as vy_ast
from vyper.exceptions import UnfoldableNode, VyperException
from vyper.semantics.namespace import get_namespace


def prefold(node: vy_ast.VyperNode) -> Any:
    if isinstance(node, vy_ast.Attribute):
        val = prefold(node.value)
        # constant struct members
        if isinstance(val, dict):
            return val[node.attr]
        return None
    elif isinstance(node, vy_ast.BinOp):
        assert isinstance(node, vy_ast.BinOp)
        left = prefold(node.left)
        right = prefold(node.right)
        if not (isinstance(left, type(right)) and isinstance(left, (int, Decimal))):
            return None
        return node.op._op(left, right)
    elif isinstance(node, vy_ast.BoolOp):
        values = [prefold(i) for i in node.values]
        if not all(isinstance(v, bool) for v in values):
            return None
        return node.op._op(values)
    elif isinstance(node, vy_ast.Call):
        # constant structs
        if len(node.args) == 1 and isinstance(node.args[0], vy_ast.Dict):
            return prefold(node.args[0])

        from vyper.builtins.functions import DISPATCH_TABLE

        # builtins
        if isinstance(node.func, vy_ast.Name):
            call_type = DISPATCH_TABLE.get(node.func.id)
            if call_type and hasattr(call_type, "evaluate"):
                try:
                    return call_type.evaluate(node).value  # type: ignore
                except (UnfoldableNode, VyperException):
                    pass
    elif isinstance(node, vy_ast.Compare):
        left = prefold(node.left)

        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            if not isinstance(node.right, (vy_ast.List, vy_ast.Tuple)):
                return None

            right = [prefold(i) for i in node.right.elements]
            if left is None or len(set([type(i) for i in right])) > 1:
                return None
            return node.op._op(left, right)

        right = prefold(node.right)
        if not (isinstance(left, type(right)) and isinstance(left, (int, Decimal))):
            return None
        return node.op._op(left, right)
    elif isinstance(node, vy_ast.Constant):
        return node.value
    elif isinstance(node, vy_ast.Dict):
        values = [prefold(v) for v in node.values]
        if any(v is None for v in values):
            return None
        return {k.id: v for (k, v) in zip(node.keys, values)}
    elif isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        val = [prefold(e) for e in node.elements]
        if None in val:
            return None
        return val
    elif isinstance(node, vy_ast.Name):
        ns = get_namespace()
        return ns._constants.get(node.id, None)
    elif isinstance(node, vy_ast.UnaryOp):
        operand = prefold(node.operand)
        if not isinstance(operand, int):
            return None
        return node.op._op(operand)

    return None
