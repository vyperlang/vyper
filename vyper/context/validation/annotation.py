from vyper import ast as vy_ast
from vyper.context.types.function import ContractFunction
from vyper.context.types.meta.event import Event
from vyper.context.validation.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_possible_types_from_node,
)
from vyper.exceptions import StructureException


class _AnnotationVisitorBase:

    """
    Annotation visitor base class.

    Annotation visitors apply metadata (such as type information) to vyper AST objects.
    Immediately after type checking a statement-level node, that node is passed to
    `StatementAnnotationVisitor`. Some expression nodes are then passed onward to
    `ExpressionAnnotationVisitor` for additional annotation.
    """

    def visit(self, node, *args):
        if isinstance(node, self.ignored_types):
            return
        # iterate over the MRO until we find a matching visitor function
        # this lets us use a single function to broadly target several
        # node types with a shared parent
        for class_ in node.__class__.mro():
            ast_type = class_.__name__
            visitor_fn = getattr(self, f"visit_{ast_type}", None)
            if visitor_fn:
                visitor_fn(node, *args)
                return
        raise StructureException(f"Cannot annotate: {node.ast_type}", node)


class StatementAnnotationVisitor(_AnnotationVisitorBase):

    ignored_types = (
        vy_ast.Break,
        vy_ast.Continue,
        vy_ast.For,
        vy_ast.Pass,
        vy_ast.Raise,
    )

    def __init__(self, fn_node: vy_ast.FunctionDef, namespace: dict) -> None:
        self.func = namespace["self"].get_member(fn_node.name, fn_node)
        self.namespace = namespace
        self.expr_visitor = ExpressionAnnotationVisitor()
        fn_node._metadata["type"] = self.func

    def visit(self, node):
        super().visit(node)

    def visit_AnnAssign(self, node):
        type_ = get_exact_type_from_node(node.target)
        self.expr_visitor.visit(node.target, type_)
        self.expr_visitor.visit(node.value, type_)

    def visit_Assert(self, node):
        self.expr_visitor.visit(node.test)

    def visit_Assign(self, node):
        type_ = get_exact_type_from_node(node.target)
        self.expr_visitor.visit(node.target, type_)
        self.expr_visitor.visit(node.value, type_)

    def visit_AugAssign(self, node):
        type_ = get_exact_type_from_node(node.target)
        self.expr_visitor.visit(node.target, type_)
        self.expr_visitor.visit(node.value, type_)

    def visit_Expr(self, node):
        self.expr_visitor.visit(node.value)

    def visit_If(self, node):
        self.expr_visitor.visit(node.test)

    def visit_Log(self, node):
        node._metadata["type"] = self.namespace[node.value.func.id]
        self.expr_visitor.visit(node.value)

    def visit_Return(self, node):
        if node.value is not None:
            self.expr_visitor.visit(node.value, self.func.return_type)


class ExpressionAnnotationVisitor(_AnnotationVisitorBase):

    ignored_types = ()

    def visit(self, node, type_=None):
        # the statement visitor sometimes passes type information about expressions
        super().visit(node, type_)

    def visit_Attribute(self, node, type_):
        base_type = get_exact_type_from_node(node.value)
        node._metadata["type"] = base_type.get_member(node.attr, None)

    def visit_BinOp(self, node, type_):
        if type_ is None:
            type_ = get_common_types(node.left, node.right)
            if len(type_) == 1:
                type_ = type_.pop()

        self.visit(node.left, type_)
        self.visit(node.right, type_)

    def visit_BoolOp(self, node, type_):
        for value in node.values:
            self.visit(value)

    def visit_Call(self, node, type_):
        call_type = get_exact_type_from_node(node.func)
        node._metadata["type"] = type_ or call_type.fetch_call_return(node)

        if isinstance(call_type, (Event, ContractFunction)):
            for arg, arg_type in zip(node.args, list(call_type.arguments.values())):
                self.visit(arg, arg_type)

    def visit_Compare(self, node, type_):
        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            if isinstance(node.right, vy_ast.List):
                type_ = get_common_types(node.left, *node.right.elements).pop()
                self.visit(node.left, type_)
                for element in node.right.elements:
                    self.visit(element, type_)
            else:
                type_ = get_exact_type_from_node(node.right)
                self.visit(node.right, type_)
                self.visit(node.left, type_.value_type)
        else:
            type_ = get_common_types(node.left, node.right).pop()
            self.visit(node.left, type_)
            self.visit(node.right, type_)

    def visit_Constant(self, node, type_):
        node._metadata["type"] = type_

    def visit_Dict(self, node, type_):
        node._metadata["type"] = type_

    def visit_Index(self, node, type_):
        self.visit(node.value, type_)

    def visit_List(self, node, type_):
        node._metadata["type"] = type_
        for element in node.elements:
            self.visit(element, type_.value_type)

    def visit_Name(self, node, type_):
        node._metadata["type"] = get_exact_type_from_node(node)

    def visit_Subscript(self, node, type_):
        base_type = get_exact_type_from_node(node.value)
        self.visit(node.slice, base_type.get_index_type(node.slice.value))
        self.visit(node.value, base_type)

    def visit_Tuple(self, node, type_):
        node._metadata["type"] = type_
        for element, subtype in zip(node.elements, type_.value_type):
            self.visit(element, subtype)

    def visit_UnaryOp(self, node, type_):
        if type_ is None:
            type_ = get_possible_types_from_node(node.operand)
            if len(type_) == 1:
                type_ = type_.pop()
        self.visit(node.operand, type_)
