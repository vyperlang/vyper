from vyper import ast as vy_ast
from vyper.context.datatypes.variables import (
    Variable,
    get_type,
)
from vyper.context.datatypes.bases import (
    IntegerType,
)
from vyper.context.datatypes.builtins import (
    BoolType,
)
from vyper.context.utils import (
    compare_types,
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
)
from vyper.context.operators import (
    validate_operation,
)


def check_functions(vy_module, namespace):
    for node in vy_module.get_children({'ast_type': "FunctionDef"}):
        TypeCheckVisitor(node, namespace)


class TypeCheckVisitor:

    ignored_types = (
        vy_ast.Break,
        vy_ast.Constant,
        vy_ast.Continue,
        vy_ast.Pass,
    )

    def __init__(self, fn_node, namespace):
        self.fn_node = fn_node
        self.namespace = namespace.copy('module')
        self.func = namespace[fn_node.name]
        self.namespace.update(self.func.arguments)
        for node in fn_node.body:
            self.visit(node)

    def visit(self, node):
        if isinstance(node, self.ignored_types):
            return
        visitor_fn = getattr(self, f'visit_{node.ast_type}', None)
        if visitor_fn is None:
            raise StructureException(
                f"Unsupported syntax for function-level namespace: {node.ast_type}", node
            )
        visitor_fn(node)

    def visit_AnnAssign(self, node):
        name = node.target.id
        self.namespace[name] = Variable(self.namespace, name, node.annotation, node.value)

    def visit_Assign(self, node):
        if len(node.targets) > 1:
            raise StructureException("Assignment statement must have one target", node.targets[1])
        target_type = get_type(self.namespace, node.targets[0])
        value_type = get_type(self.namespace, node.value)
        compare_types(target_type, value_type, node)

    def visit_AugAssign(self, node):
        target_type = get_type(self.namespace, node.target)
        target_type.validate_op(node)

        value_type = get_type(self.namespace, node.value)
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
            validate_operation(self.namespace, node)
        elif not isinstance(get_type(self.namespace, node.test), (BoolType, vy_ast.NameConstant)):
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
        validate_operation(self.namespace, node)
        # TODO what about when node.operand is BinOp ?
        # get_type(self.namespace, node.operand).validate_op(node)

    def visit_BinOp(self, node):
        validate_operation(self.namespace, node)

    def visit_Compare(self, node):
        validate_operation(self.namespace, node)

    def visit_Call(self, node):
        # TODO
        pass

    def visit_If(self, node):
        self.visit(node.test)
        for n in node.body + node.orelse:
            self.visit(n)

    def visit_For(self, node):

        # iteration over a variable
        if isinstance(node.iter, vy_ast.Name):
            iter_var = self.namespace[node.iter.id]
            if not isinstance(iter_var.type, list):
                raise
            target_type = iter_var.type

        # iteration over a literal list
        elif isinstance(node.iter, vy_ast.List):
            iter_values = node.iter.elts
            if not iter_values:
                raise StructureException("Cannot iterate empty array", node.iter)
            get_type(self.namespace, node.iter)
            # TODO this might be a constant, not a type, how to handle var declaration?

        # iteration via range()
        elif isinstance(node.iter, vy_ast.Call):
            if node.iter.func.id != "range":
                raise StructureException(
                    "Cannot iterate over the result of a function call", node.iter
                )
            check_call_args(node.iter, (1, 2))

            args = node.iter.args
            if len(args) == 1:
                if not isinstance(args[0], vy_ast.Int):
                    raise  # arg must be literal
                # arg must be a literal
                pass

            elif isinstance(args[0], vy_ast.Name):
                target_type = get_type(self.namespace, args[0])
                if not isinstance(target_type, IntegerType):
                    raise
                if not isinstance(args[1], vy_ast.BinOp) or not isinstance(args[1].op, vy_ast.Add):
                    raise
                if args[0] != args[1].left:
                    raise

            else:
                if args[0].value < args[1].value:
                    raise
                target_type = None  # TODO how to handle the type when both args are literals?
        else:
            raise StructureException("Invalid type for iteration", node.iter)

        self.namespace[node.target.id] = Variable(self.namespace, node.target.id, target_type, None)

        for n in node.body:
            self.visit(n)
        del self.namespace[node.target.id]

    def visit_Attribute(self, node):
        get_type(self.namespace, node)

    def visit_Name(self, node):
        get_type(self.namespace, node)

    def visit_Subscript(self, node):
        get_type(self.namespace, node)

    def visit_List(self, node):
        get_type(self.namespace, node)


def _check_operand(namespace, node, node_list, validation_fn_name):
    node_list = [get_type(namespace, i) for i in node_list]

    literals = [i for i in node_list if isinstance(i, vy_ast.Constant)]
    assigned = [i for i in node_list if i not in literals]

    if not assigned:
        # TODO this is wrong for comparisons
        if not isinstance(node.left, (vy_ast.Int, vy_ast.Decimal)):
            raise StructureException(
                f"Invalid literal type for operation: {node.left.ast_type}", node
            )
    else:
        getattr(assigned[0], validation_fn_name)(node)
    compare_types(node_list[0], node_list[1], node)
