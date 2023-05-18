from vyper import ast as vy_ast
from vyper.exceptions import StructureException, TypeCheckFailure
from vyper.semantics.analysis.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_possible_types_from_node,
)
from vyper.semantics.types import TYPE_T, BoolT, EnumT, EventT, SArrayT, StructT, is_type_t
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT


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
    ignored_types = (vy_ast.Break, vy_ast.Continue, vy_ast.Pass, vy_ast.Raise)

    def __init__(self, fn_node: vy_ast.FunctionDef, namespace: dict) -> None:
        self.func = fn_node._metadata["type"]
        self.namespace = namespace
        self.expr_visitor = ExpressionAnnotationVisitor(self.func)

        assert self.func.n_keyword_args == len(fn_node.args.defaults)
        for kwarg in self.func.keyword_args:
            self.expr_visitor.visit(kwarg.default_value, kwarg.typ)

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

    def visit_For(self, node):
        if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
            self.expr_visitor.visit(node.iter)
        # typecheck list literal as static array
        if isinstance(node.iter, vy_ast.List):
            value_type = get_common_types(*node.iter.elements).pop()
            len_ = len(node.iter.elements)
            self.expr_visitor.visit(node.iter, SArrayT(value_type, len_))

        if isinstance(node.iter, vy_ast.Call) and node.iter.func.id == "range":
            iter_type = node.target._metadata["type"]
            for a in node.iter.args:
                self.expr_visitor.visit(a, iter_type)


class ExpressionAnnotationVisitor(_AnnotationVisitorBase):
    ignored_types = ()

    def __init__(self, fn_node: ContractFunctionT):
        self.func = fn_node

    def visit(self, node, type_=None):
        # the statement visitor sometimes passes type information about expressions
        super().visit(node, type_)

    def visit_Attribute(self, node, type_):
        type_ = get_exact_type_from_node(node)
        node._metadata["type"] = type_
        self.visit(node.value, None)

    def visit_BinOp(self, node, type_):
        if type_ is None:
            type_ = get_common_types(node.left, node.right)
            if len(type_) == 1:
                type_ = type_.pop()
        node._metadata["type"] = type_

        self.visit(node.left, type_)
        self.visit(node.right, type_)

    def visit_BoolOp(self, node, type_):
        for value in node.values:
            self.visit(value)

    def visit_Call(self, node, type_):
        call_type = get_exact_type_from_node(node.func)
        node_type = type_ or call_type.fetch_call_return(node)
        node._metadata["type"] = node_type
        self.visit(node.func)

        if isinstance(call_type, ContractFunctionT):
            # function calls
            if call_type.is_internal:
                self.func.called_functions.add(call_type)
            for arg, typ in zip(node.args, call_type.argument_types):
                self.visit(arg, typ)
            for kwarg in node.keywords:
                # We should only see special kwargs
                self.visit(kwarg.value, call_type.call_site_kwargs[kwarg.arg].typ)

        elif is_type_t(call_type, EventT):
            # events have no kwargs
            for arg, typ in zip(node.args, list(call_type.typedef.arguments.values())):
                self.visit(arg, typ)
        elif is_type_t(call_type, StructT):
            # struct ctors
            # ctors have no kwargs
            for value, arg_type in zip(
                node.args[0].values, list(call_type.typedef.members.values())
            ):
                self.visit(value, arg_type)
        elif isinstance(call_type, MemberFunctionT):
            assert len(node.args) == len(call_type.arg_types)
            for arg, arg_type in zip(node.args, call_type.arg_types):
                self.visit(arg, arg_type)
        else:
            # builtin functions
            arg_types = call_type.infer_arg_types(node)
            for arg, arg_type in zip(node.args, arg_types):
                self.visit(arg, arg_type)
            kwarg_types = call_type.infer_kwarg_types(node)
            for kwarg in node.keywords:
                self.visit(kwarg.value, kwarg_types[kwarg.arg])

    def visit_Compare(self, node, type_):
        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            if isinstance(node.right, vy_ast.List):
                type_ = get_common_types(node.left, *node.right.elements).pop()
                self.visit(node.left, type_)
                rlen = len(node.right.elements)
                self.visit(node.right, SArrayT(type_, rlen))
            else:
                type_ = get_exact_type_from_node(node.right)
                self.visit(node.right, type_)
                if isinstance(type_, EnumT):
                    self.visit(node.left, type_)
                else:
                    # array membership
                    self.visit(node.left, type_.value_type)
        else:
            type_ = get_common_types(node.left, node.right).pop()
            self.visit(node.left, type_)
            self.visit(node.right, type_)

    def visit_Constant(self, node, type_):
        if type_ is None:
            possible_types = get_possible_types_from_node(node)
            if len(possible_types) == 1:
                type_ = possible_types.pop()
        node._metadata["type"] = type_

    def visit_Dict(self, node, type_):
        node._metadata["type"] = type_

    def visit_Index(self, node, type_):
        self.visit(node.value, type_)

    def visit_List(self, node, type_):
        if type_ is None:
            type_ = get_possible_types_from_node(node)
            # CMC 2022-04-14 this seems sus. try to only annotate
            # if get_possible_types only returns 1 type
            if len(type_) >= 1:
                type_ = type_.pop()
        node._metadata["type"] = type_
        for element in node.elements:
            self.visit(element, type_.value_type)

    def visit_Name(self, node, type_):
        if isinstance(type_, TYPE_T):
            node._metadata["type"] = type_
        else:
            node._metadata["type"] = get_exact_type_from_node(node)

    def visit_Subscript(self, node, type_):
        node._metadata["type"] = type_

        if isinstance(type_, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        if isinstance(node.value, vy_ast.List):
            possible_base_types = get_possible_types_from_node(node.value)

            if len(possible_base_types) == 1:
                base_type = possible_base_types.pop()

            elif type_ is not None and len(possible_base_types) > 1:
                for possible_type in possible_base_types:
                    if type_.compare_type(possible_type.value_type):
                        base_type = possible_type
                        break
                else:
                    # this should have been caught in
                    # `get_possible_types_from_node` but wasn't.
                    raise TypeCheckFailure(f"Expected {type_} but it is not a possible type", node)

        else:
            base_type = get_exact_type_from_node(node.value)

        # get the correct type for the index, it might
        # not be base_type.key_type
        index_types = get_possible_types_from_node(node.slice.value)
        index_type = index_types.pop()

        self.visit(node.slice, index_type)
        self.visit(node.value, base_type)

    def visit_Tuple(self, node, type_):
        node._metadata["type"] = type_

        if isinstance(type_, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        for element, subtype in zip(node.elements, type_.member_types):
            self.visit(element, subtype)

    def visit_UnaryOp(self, node, type_):
        if type_ is None:
            type_ = get_possible_types_from_node(node.operand)
            if len(type_) == 1:
                type_ = type_.pop()
        node._metadata["type"] = type_
        self.visit(node.operand, type_)

    def visit_IfExp(self, node, type_):
        if type_ is None:
            ts = get_common_types(node.body, node.orelse)
            if len(type_) == 1:
                type_ = ts.pop()

        node._metadata["type"] = type_
        self.visit(node.test, BoolT())
        self.visit(node.body, type_)
        self.visit(node.orelse, type_)
