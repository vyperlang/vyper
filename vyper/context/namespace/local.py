from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.variable import (
    Variable,
    get_variable_from_nodes,
)
from vyper.context.typecheck import (
    compare_types,
    get_type_from_node,
    get_type_from_operation,
    get_value_from_node,
)
from vyper.context.types.bases import (
    IntegerType,
)
from vyper.context.types.builtins import (
    BoolType,
)
from vyper.context.utils import (
    VyperNodeVisitorBase,
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
    VariableDeclarationException,
)


class FunctionNodeVisitor(VyperNodeVisitorBase):

    ignored_types = (
        vy_ast.Break,
        vy_ast.Constant,
        vy_ast.Continue,
        vy_ast.Pass,
    )
    scope_name = "function"

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.func = namespace["self"].get_member(fn_node)
        self.namespace = self.func.namespace
        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type and not fn_node.get_children({'ast_type': "Return"}):
            raise StructureException(f"{self.func.name} is missing a return statement", fn_node)

    def visit_AnnAssign(self, node):
        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )
        name = node.target.id
        if name in self.namespace["self"].members:
            raise VariableDeclarationException(
                "Variable declaration shadows an existing storage variable", node
            )
        var = get_variable_from_nodes(self.namespace, name, node.annotation, node.value)
        self.namespace[name] = var

    def visit_Assign(self, node):
        if len(node.targets) > 1:
            raise StructureException("Assignment statement must have one target", node.targets[1])

        # TODO prevent assignment to constants
        target_var = get_value_from_node(self.namespace, node.targets[0])
        if not isinstance(target_var, Variable) or target_var.is_constant:
            raise StructureException(f"Cannot modify value of a constant", node)

        value_type = get_type_from_node(self.namespace, node.value)
        compare_types(target_var.type, value_type, node)

    def visit_AugAssign(self, node):
        target_type = get_type_from_node(self.namespace, node.target)
        target_type.validate_numeric_op(node)

        value_type = get_type_from_node(self.namespace, node.value)
        compare_types(target_type, value_type, node)

    def visit_Raise(self, node):
        if not node.exc:
            raise StructureException("Raise must have a reason", node)
        if not isinstance(node.exc, vy_ast.Str) or len(node.exc.value) > 32:
            raise StructureException("Reason must be a string of 32 characters or less", node.exc)

    def visit_Assert(self, node):
        if node.msg and (not isinstance(node.msg, vy_ast.Str) or len(node.msg.value) > 32):
            raise StructureException("Reason must be a string of 32 characters or less", node.msg)
        if isinstance(node.test, (vy_ast.BoolOp, vy_ast.Compare)):
            get_type_from_operation(self.namespace, node)
        elif not isinstance(
            get_type_from_node(self.namespace, node.test),
            (BoolType, vy_ast.NameConstant)
        ):
            raise

    def visit_Delete(self, node):
        # TODO can we just block this at the AST generation stage?
        raise StructureException("Deleting is not supported, use built-in clear() function", node)

    def visit_Return(self, node):
        values = node.value
        if values is None:
            if self.func.return_type:
                raise StructureException("Return statement is missing a value", node)
            return
        if values and self.func.return_type is None:
            raise StructureException("Function does not return any values", node)
        if isinstance(values, vy_ast.Tuple):
            values = values.elts
        compare_types(self.func.return_type, values, node)

    def visit_Expr(self, node):
        self.visit(node.value)

    def visit_UnaryOp(self, node):
        get_type_from_operation(self.namespace, node)
        # TODO what about when node.operand is BinOp ?
        # get_type(self.namespace, node.operand).validate_op(node)

    def visit_BinOp(self, node):
        get_type_from_operation(self.namespace, node)

    def visit_Compare(self, node):
        get_type_from_operation(self.namespace, node)

    def visit_Call(self, node):
        value = get_value_from_node(self.namespace, node.func)
        value.validate_call(node)

    def visit_If(self, node):
        self.visit(node.test)
        for n in node.body + node.orelse:
            self.visit(n)

    def visit_For(self, node):
        namespace = self.namespace.copy(node.enclosing_scope)

        # iteration over a variable
        if isinstance(node.iter, vy_ast.Name):
            iter_var = self.namespace[node.iter.id]
            if not isinstance(iter_var.type, list):
                raise
            target_type = iter_var.type[0]

        # iteration over a literal list
        elif isinstance(node.iter, vy_ast.List):
            iter_values = node.iter.elts
            if not iter_values:
                raise StructureException("Cannot iterate empty array", node.iter)
            target_type = get_type_from_node(self.namespace, node.iter)[0]

        # iteration via range()
        elif isinstance(node.iter, vy_ast.Call):
            if node.iter.func.id != "range":
                raise StructureException(
                    "Cannot iterate over the result of a function call", node.iter
                )
            check_call_args(node.iter, (1, 2))

            args = node.iter.args
            target_type = get_type_from_node(self.namespace, args[0])
            if len(args) == 1:
                # range(10)
                if not isinstance(args[0], vy_ast.Int):
                    raise StructureException("Range argument must be integer", args[0])

            elif isinstance(args[0], vy_ast.Name):
                # range(x, x + 10)
                if not isinstance(target_type, IntegerType):
                    raise
                if not isinstance(args[1], vy_ast.BinOp) or not isinstance(args[1].op, vy_ast.Add):
                    raise
                if args[0] != args[1].left:
                    raise
                if not isinstance(args[1].right, vy_ast.Int):
                    raise
            else:
                # range(1, 10)
                if args[0].value >= args[1].value:
                    raise
                # TODO check that args[0] + args[1] doesn't overflow

        else:
            raise StructureException("Invalid type for iteration", node.iter)

        var = Variable(self.namespace, node.target.id, node.enclosing_scope, target_type)
        self.namespace[node.target.id] = var

        for n in node.body:
            self.visit(n)
        self.namespace = namespace

    def visit_Attribute(self, node):
        get_type_from_node(self.namespace, node)

    def visit_Name(self, node):
        get_type_from_node(self.namespace, node)

    def visit_Subscript(self, node):
        get_type_from_node(self.namespace, node)

    def visit_List(self, node):
        get_type_from_node(self.namespace, node)
