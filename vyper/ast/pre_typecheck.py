from decimal import Decimal
from typing import Any

from vyper.ast import nodes as vy_ast
from vyper.exceptions import UnfoldableNode, VyperException
from vyper.semantics.namespace import get_namespace


def prefold(node: vy_ast.VyperNode) -> Any:
    if isinstance(node, vy_ast.Attribute):
        val = prefold(node.value)
        # constant struct members
        if isinstance(val, dict):
            return val[node.attr]

    elif isinstance(node, vy_ast.BinOp):
        left = prefold(node.left)
        right = prefold(node.right)
        if isinstance(left, type(right)) and isinstance(left, (int, Decimal)):
            return node.op._op(left, right)

    elif isinstance(node, vy_ast.BoolOp):
        values = [prefold(i) for i in node.values]
        if all(isinstance(v, bool) for v in values):
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
        if isinstance(left, type(right)) and isinstance(left, (int, Decimal)):
            return node.op._op(left, right)

    elif isinstance(node, vy_ast.Constant):
        return node.value

    elif isinstance(node, vy_ast.Dict):
        values = [prefold(v) for v in node.values]
        if not any(v is None for v in values):
            return {k.id: v for (k, v) in zip(node.keys, values)}

    elif isinstance(node, (vy_ast.List, vy_ast.Tuple)):
        val = [prefold(e) for e in node.elements]
        if None not in val:
            return val

    elif isinstance(node, vy_ast.Name):
        ns = get_namespace()
        return ns._constants.get(node.id)

    elif isinstance(node, vy_ast.UnaryOp):
        operand = prefold(node.operand)
        if isinstance(operand, int):
            return node.op._op(operand)

    return None
