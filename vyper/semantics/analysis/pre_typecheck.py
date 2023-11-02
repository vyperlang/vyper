from vyper import ast as vy_ast
from vyper.exceptions import UnfoldableNode, VyperException
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.utils import get_folded_value


def pre_typecheck(node: vy_ast.VyperNode) -> None:
    PreTypecheckVisitor(node)


class PreTypecheckVisitor(VyperNodeVisitorBase):
    ignored_types = (
        vy_ast.Pass,
        vy_ast.ImplementsDecl,
        vy_ast.EnumDef,
        vy_ast.Import,
        vy_ast.ImportFrom,
        vy_ast.Break,
        vy_ast.Continue,
    )
    scope_name = "module"

    def __init__(self, node: vy_ast.VyperNode) -> None:
        self.constants = {}

        if isinstance(node, vy_ast.Module):
            module_nodes = node.body.copy()
            const_var_decls = [
                n for n in module_nodes if isinstance(n, vy_ast.VariableDecl) and n.is_constant
            ]

            while const_var_decls:
                derived_nodes = 0

                for c in const_var_decls:
                    name = c.get("target.id")
                    # Handle syntax errors downstream
                    if c.value is None:
                        continue

                    self.visit(c.value)

                    val = get_folded_value(c.value)

                    # note that if a constant is redefined, its value will be overwritten,
                    # but it is okay because the syntax error is handled downstream
                    if val is not None:
                        self.constants[name] = val
                        derived_nodes += 1
                        const_var_decls.remove(c)

                if not derived_nodes:
                    break

        self.visit(node)

    def visit(self, node):
        super().visit(node)

    # Module-level declarations

    def visit_EventDef(self, node):
        for n in node.body:
            if isinstance(n, vy_ast.AnnAssign):
                self.visit(n.annotation)

    def visit_FunctionDef(self, node):
        # visit type annotations of arguments
        # e.g. def foo(a: DynArray[uint256, 2 ** 8]): ...
        for arg in node.args.args:
            if arg.annotation:
                self.visit(arg.annotation)

        for kwarg in node.args.defaults:
            self.visit(kwarg)

        if node.returns:
            self.visit(node.returns)

        for n in node.body:
            self.visit(n)

    def visit_InterfaceDef(self, node):
        for n in node.body:
            self.visit(n)

    def visit_Module(self, node):
        for n in node.body:
            self.visit(n)

    def visit_StructDef(self, node):
        for n in node.body:
            if isinstance(node, vy_ast.AnnAssign):
                self.visit(n.annotation)

    def visit_VariableDecl(self, node):
        self.visit(node.annotation)
        if node.is_constant and node.value:
            self.visit(node.value)

    # Stmts

    def visit_AnnAssign(self, node):
        self.visit(node.target)
        self.visit(node.value)
        self.visit(node.annotation)

    def visit_Assert(self, node):
        self.visit(node.test)
        if node.msg:
            self.visit(node.msg)

    def _assign_helper(self, node):
        self.visit(node.target)
        self.visit(node.value)

    def visit_Assign(self, node):
        self._assign_helper(node)

    def visit_AugAssign(self, node):
        self._assign_helper(node)

    def visit_Expr(self, node):
        self.visit(node.value)

    def visit_For(self, node):
        for n in node.body:
            self.visit(n)

        self.visit(node.iter)
        self.visit(node.target)

    def visit_If(self, node):
        for n in node.body:
            self.visit(n)
        for n in node.orelse:
            self.visit(n)

    def visit_Log(self, node):
        self.visit(node.value)

    def visit_Raise(self, node):
        if node.exc:
            self.visit(node.exc)

    def visit_Return(self, node):
        if node.value:
            self.visit(node.value)

    # Expr

    def visit_keyword(self, node):
        self.visit(node.arg)
        self.visit(node.value)

    def visit_Attribute(self, node):
        self.visit(node.value)
        value_node = get_folded_value(node.value)
        if isinstance(value_node, vy_ast.Dict):
            for k, v in zip(value_node.keys, value_node.values):
                if k.id == node.attr:
                    node._metadata["folded_value"] = v
                    return

    def visit_BinOp(self, node):
        self.visit(node.left)
        self.visit(node.right)

        left = get_folded_value(node.left)
        right = get_folded_value(node.right)
        if isinstance(left, type(right)) and isinstance(left, (vy_ast.Int, vy_ast.Decimal)):
            if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)) and not (
                0 <= right.value <= 256
            ):
                return
            value = node.op._op(left.value, right.value)
            node._metadata["folded_value"] = type(left).from_node(node, value=value)

    def visit_BoolOp(self, node):
        for i in node.values:
            self.visit(i)

        values = [get_folded_value(i) for i in node.values]
        if all(isinstance(v, vy_ast.NameConstant) for v in values):
            value = node.op._op([v.value for v in values])
            node._metadata["folded_value"] = vy_ast.NameConstant.from_node(node, value=value)

    def visit_Call(self, node):
        for arg in node.args:
            self.visit(arg)
        for kwarg in node.keywords:
            self.visit(kwarg.value)

        # constant structs
        if len(node.args) == 1 and isinstance(node.args[0], vy_ast.Dict):
            values = [get_folded_value(v) for v in node.args[0].values]
            if not any(v is None for v in values):
                node._metadata["folded_value"] = type(node).from_node(
                    node,
                    func=node.func,
                    args=[
                        vy_ast.Dict.from_node(node.args[0], keys=node.args[0].keys, values=values)
                    ],
                )

        from vyper.builtins.functions import DISPATCH_TABLE

        # builtins
        if isinstance(node.func, vy_ast.Name):
            func_name = node.func.id

            call_type = DISPATCH_TABLE.get(func_name)
            if call_type and hasattr(call_type, "evaluate"):
                try:
                    node._metadata["folded_value"] = call_type.evaluate(
                        node, skip_typecheck=True
                    )  # type: ignore
                    return
                except (UnfoldableNode, VyperException):
                    pass

    def visit_Compare(self, node):
        self.visit(node.left)
        self.visit(node.right)

        left = get_folded_value(node.left)

        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            if not isinstance(node.right, (vy_ast.List, vy_ast.Tuple)):
                return

            right = [get_folded_value(i) for i in node.right.elements]
            if left is None or len(set([type(i) for i in right])) > 1:
                return
            value = node.op._op(left.value, [i.value for i in right])
            node._metadata["folded_value"] = vy_ast.NameConstant.from_node(value=value)
            return

        right = get_folded_value(node)
        if isinstance(left, type(right)) and isinstance(left, (vy_ast.Int, vy_ast.Decimal)):
            value = node.op._op(left.value, right.value)
            node._metadata["folded_value"] = vy_ast.NameConstant.from_node(value=value)

    def visit_Constant(self, node):
        pass

    def visit_Dict(self, node):
        for v in node.values:
            self.visit(v)

    def visit_Index(self, node):
        self.visit(node.value)

    # repeated code for List and Tuple
    def _subscriptable_helper(self, node):
        for e in node.elements:
            self.visit(e)

        values = [get_folded_value(e) for e in node.elements]
        if None not in values:
            node._metadata["folded_value"] = type(node).from_node(node, elts=values)

    def visit_List(self, node):
        self._subscriptable_helper(node)

    def visit_Name(self, node):
        if node.id in self.constants:
            node._metadata["folded_value"] = self.constants.get(node.id)

    def visit_Subscript(self, node):
        self.visit(node.slice)
        self.visit(node.value)

        index = get_folded_value(node.slice)
        sliced = get_folded_value(node.value)
        if None not in (sliced, index):
            node._metadata["folded_value"] = sliced.elements[index.value]

    def visit_Tuple(self, node):
        self._subscriptable_helper(node)

    def visit_UnaryOp(self, node):
        self.visit(node.operand)
        val = get_folded_value(node.operand)
        if isinstance(val, vy_ast.Constant):
            value = node.op._op(val.value)
            node._metadata["folded_value"] = type(val).from_node(node, value=value)

    def visit_IfExp(self, node):
        self.visit(node.test)
        self.visit(node.body)
        self.visit(node.orelse)
