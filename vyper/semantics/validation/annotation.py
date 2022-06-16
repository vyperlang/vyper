from vyper import ast as vy_ast
from vyper.exceptions import StructureException
from vyper.semantics.types import ArrayDefinition
from vyper.semantics.types.function import ContractFunction, MemberFunctionDefinition
from vyper.semantics.types.user.enum import EnumDefinition
from vyper.semantics.types.user.event import Event
from vyper.semantics.types.user.struct import StructPrimitive
from vyper.semantics.types.utils import TypeTypeDefinition
from vyper.semantics.validation.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_possible_types_from_node,
)


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

        assert len(self.func.kwarg_keys) == len(fn_node.args.defaults)
        for kw, val in zip(self.func.kwarg_keys, fn_node.args.defaults):
            self.expr_visitor.visit(val, self.func.arguments[kw])

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
            self.expr_visitor.visit(node.iter, ArrayDefinition(value_type, len_))

        if isinstance(node.iter, vy_ast.Call) and node.iter.func.id == "range":
            iter_type = node.target._metadata["type"]
            for a in node.iter.args:
                self.expr_visitor.visit(a, iter_type)


class ExpressionAnnotationVisitor(_AnnotationVisitorBase):

    ignored_types = ()

    def __init__(self, fn_node: ContractFunction):
        self.func = fn_node

    def visit(self, node, type_=None):
        # the statement visitor sometimes passes type information about expressions
        super().visit(node, type_)

    def visit_Attribute(self, node, type_):
        base_type = get_exact_type_from_node(node.value)
        node._metadata["type"] = base_type.get_member(node.attr, node)
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

    def visit_Bytes(self, node, type_):
        node._metadata["type"] = type_

    def visit_Call(self, node, type_):
        call_type = get_exact_type_from_node(node.func)
        node_type = type_ or call_type.fetch_call_return(node)
        node._metadata["type"] = node_type
        self.visit(node.func)

        if isinstance(call_type, ContractFunction) and call_type.is_internal:
            self.func.called_functions.add(call_type)

        if isinstance(call_type, (Event, ContractFunction)):
            # events and function calls
            for arg, arg_type in zip(node.args, list(call_type.arguments.values())):
                self.visit(arg, arg_type)
            for kwarg in node.keywords:
                # We should only see special kwargs
                self.visit(kwarg.value, call_type.call_site_kwargs[kwarg.arg].typ)
        elif isinstance(call_type, StructPrimitive):
            # literal structs
            for value, arg_type in zip(node.args[0].values, list(call_type.members.values())):
                self.visit(value, arg_type)
        elif isinstance(call_type, MemberFunctionDefinition):
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
                self.visit(node.right, ArrayDefinition(type_, rlen))
            else:
                type_ = get_exact_type_from_node(node.right)
                self.visit(node.right, type_)
                if isinstance(type_, EnumDefinition):
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

    def visit_Hex(self, node, type_):
        node._metadata["type"] = type_

    def visit_Index(self, node, type_):
        self.visit(node.value, type_)

    def visit_Int(self, node, type_):
        node._metadata["type"] = type_

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
        if isinstance(type_, TypeTypeDefinition):
            node._metadata["type"] = type_
        else:
            node._metadata["type"] = get_exact_type_from_node(node)

    def visit_Subscript(self, node, type_):
        node._metadata["type"] = type_

        if isinstance(type_, TypeTypeDefinition):
            # don't recurse; can't annotate AST children of type definition
            return

        if isinstance(node.value, vy_ast.List):
            possible_base_types = get_possible_types_from_node(node.value)

            if len(possible_base_types) == 1:
                base_type = possible_base_types.pop()

            elif type_ is not None and len(possible_base_types) > 1:
                for possible_type in possible_base_types:
                    if isinstance(possible_type.value_type, type(type_)):
                        base_type = possible_type
                        break

        else:
            base_type = get_exact_type_from_node(node.value)

        self.visit(node.slice, base_type.get_index_type())
        self.visit(node.value, base_type)

    def visit_Tuple(self, node, type_):
        node._metadata["type"] = type_

        if isinstance(type_, TypeTypeDefinition):
            # don't recurse; can't annotate AST children of type definition
            return

        for element, subtype in zip(node.elements, type_.value_type):
            self.visit(element, subtype)

    def visit_UnaryOp(self, node, type_):
        if type_ is None:
            type_ = get_possible_types_from_node(node.operand)
            if len(type_) == 1:
                type_ = type_.pop()
        node._metadata["type"] = type_
        self.visit(node.operand, type_)
