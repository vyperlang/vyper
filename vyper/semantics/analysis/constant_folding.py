from vyper import ast as vy_ast
from vyper.exceptions import InvalidLiteral, UnfoldableNode, VyperException
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.namespace import get_namespace


def constant_fold(module_ast: vy_ast.Module):
    ConstantFolder(module_ast).run()


class ConstantFolder(VyperNodeVisitorBase):
    def __init__(self, module_ast):
        self._constants = {}
        self._module_ast = module_ast

    def run(self):
        self._get_constants()
        self.visit(self._module_ast)

    def _get_constants(self):
        module = self._module_ast
        const_var_decls = module.get_children(vy_ast.VariableDecl, {"is_constant": True})

        while True:
            n_processed = 0

            for c in const_var_decls.copy():
                # visit the entire constant node in case its type annotation
                # has unfolded constants in it.
                self.visit(c)

                assert c.value is not None  # guaranteed by VariableDecl.validate()
                try:
                    val = c.value.get_folded_value()
                except UnfoldableNode:
                    # not foldable, maybe it depends on other constants
                    # so try again later
                    continue

                # note that if a constant is redefined, its value will be
                # overwritten, but it is okay because the error is handled
                # downstream
                name = c.target.id
                self._constants[name] = val

                n_processed += 1
                const_var_decls.remove(c)

            if n_processed == 0:
                # this condition means that there are some constant vardecls
                # whose values are not foldable. this can happen for struct
                # and interface constants for instance. these are valid constant
                # declarations, but we just can't fold them at this stage.
                break

    def visit(self, node):
        if node.has_folded_value:
            return node.get_folded_value()

        for c in node.get_children():
            try:
                self.visit(c)
            except UnfoldableNode:
                # ignore bubbled up exceptions
                pass

        try:
            for class_ in node.__class__.mro():
                ast_type = class_.__name__

                visitor_fn = getattr(self, f"visit_{ast_type}", None)
                if visitor_fn:
                    folded_value = visitor_fn(node)
                    node._set_folded_value(folded_value)
                    return folded_value
        except UnfoldableNode:
            # ignore bubbled up exceptions
            pass

        return node

    def visit_Constant(self, node) -> vy_ast.ExprNode:
        return node

    def visit_Name(self, node) -> vy_ast.ExprNode:
        try:
            return self._constants[node.id]
        except KeyError:
            raise UnfoldableNode("unknown name", node)

    def visit_Attribute(self, node) -> vy_ast.ExprNode:
        namespace = get_namespace()
        path = []
        value = node.value
        while isinstance(value, vy_ast.Attribute):
            path.append(value.attr)
            value = value.value

        path.reverse()

        if not isinstance(value, vy_ast.Name):
            raise UnfoldableNode("not a module", value)

        # not super type-safe but we don't care. just catch AttributeErrors
        # and move on
        try:
            module_t = namespace[value.id].module_t

            for module_name in path:
                module_t = module_t.members[module_name].module_t

            varinfo = module_t.get_member(node.attr, node)

            return varinfo.decl_node.value.get_folded_value()
        except (VyperException, AttributeError, KeyError):
            raise UnfoldableNode("not a module")

    def visit_UnaryOp(self, node):
        operand = node.operand.get_folded_value()

        if isinstance(node.op, vy_ast.Not) and not isinstance(operand, vy_ast.NameConstant):
            raise UnfoldableNode("not a boolean!", node.operand)
        if isinstance(node.op, vy_ast.USub) and not isinstance(operand, vy_ast.Num):
            raise UnfoldableNode("not a number!", node.operand)
        if isinstance(node.op, vy_ast.Invert) and not isinstance(operand, vy_ast.Int):
            raise UnfoldableNode("not an int!", node.operand)

        value = node.op._op(operand.value)
        return type(operand).from_node(node, value=value)

    def visit_BinOp(self, node):
        left, right = [i.get_folded_value() for i in (node.left, node.right)]
        if type(left) is not type(right):
            raise UnfoldableNode("invalid operation", node)
        if not isinstance(left, vy_ast.Num):
            raise UnfoldableNode("not a number!", node.left)

        # this validation is performed to prevent the compiler from hanging
        # on very large shifts and improve the error message for negative
        # values.
        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)) and not (0 <= right.value <= 256):
            raise InvalidLiteral("Shift bits must be between 0 and 256", node.right)

        value = node.op._op(left.value, right.value)
        return type(left).from_node(node, value=value)

    def visit_BoolOp(self, node):
        values = [v.get_folded_value() for v in node.values]

        if any(not isinstance(v, vy_ast.NameConstant) for v in values):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        values = [v.value for v in values]
        value = node.op._op(values)
        return vy_ast.NameConstant.from_node(node, value=value)

    def visit_Compare(self, node):
        left, right = [i.get_folded_value() for i in (node.left, node.right)]
        if not isinstance(left, vy_ast.Constant):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        # CMC 2022-08-04 we could probably remove these evaluation rules as they
        # are taken care of in the IR optimizer now.
        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            if not isinstance(right, vy_ast.List):
                raise UnfoldableNode("Node contains invalid field(s) for evaluation")
            if next((i for i in right.elements if not isinstance(i, vy_ast.Constant)), None):
                raise UnfoldableNode("Node contains invalid field(s) for evaluation")
            if len(set([type(i) for i in right.elements])) > 1:
                raise UnfoldableNode("List contains multiple literal types")
            value = node.op._op(left.value, [i.value for i in right.elements])
            return vy_ast.NameConstant.from_node(node, value=value)

        if not isinstance(left, type(right)):
            raise UnfoldableNode("Cannot compare different literal types")

        # this is maybe just handled in the type checker.
        if not isinstance(node.op, (vy_ast.Eq, vy_ast.NotEq)) and not isinstance(left, vy_ast.Num):
            raise UnfoldableNode(
                f"Invalid literal types for {node.op.description} comparison", node
            )

        value = node.op._op(left.value, right.value)
        return vy_ast.NameConstant.from_node(node, value=value)

    def visit_List(self, node) -> vy_ast.ExprNode:
        elements = [e.get_folded_value() for e in node.elements]
        return type(node).from_node(node, elements=elements)

    def visit_Tuple(self, node) -> vy_ast.ExprNode:
        elements = [e.get_folded_value() for e in node.elements]
        return type(node).from_node(node, elements=elements)

    def visit_Dict(self, node) -> vy_ast.ExprNode:
        values = [v.get_folded_value() for v in node.values]
        return type(node).from_node(node, values=values)

    def visit_Call(self, node) -> vy_ast.ExprNode:
        if not isinstance(node.func, vy_ast.Name):
            raise UnfoldableNode("not a builtin", node)

        namespace = get_namespace()

        func_name = node.func.id
        if func_name not in namespace:
            raise UnfoldableNode("unknown", node)

        varinfo = namespace[func_name]
        if not isinstance(varinfo, VarInfo):
            raise UnfoldableNode("unfoldable", node)

        typ = varinfo.typ
        # TODO: rename to vyper_type.try_fold_call_expr
        if not hasattr(typ, "_try_fold"):
            raise UnfoldableNode("unfoldable", node)
        return typ._try_fold(node)

    def visit_Subscript(self, node) -> vy_ast.ExprNode:
        slice_ = node.slice.get_folded_value()
        value = node.value.get_folded_value()

        if not isinstance(value, vy_ast.List):
            raise UnfoldableNode("Subscript object is not a literal list")

        elements = value.elements
        if len(set([type(i) for i in elements])) > 1:
            raise UnfoldableNode("List contains multiple node types")

        if not isinstance(slice_, vy_ast.Int):
            raise UnfoldableNode("invalid index type", slice_)

        idx = slice_.value
        if idx < 0 or idx >= len(elements):
            raise UnfoldableNode("invalid index value")

        return elements[idx]
