from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions import (
    Literal,
    Reference,
    get_definition_from_node,
    get_literal_or_raise,
    get_variable_from_nodes,
)
from vyper.context.types.bases.data import (
    BoolBase,
    IntegerBase,
)
from vyper.context.utils import (
    VyperNodeVisitorBase,
    compare_types,
    is_subtype,
    validate_call_args,
)
from vyper.exceptions import (
    ConstancyViolation,
    ExceptionList,
    FunctionDeclarationException,
    InvalidLiteral,
    InvalidType,
    NamespaceCollision,
    StructureException,
    VariableDeclarationException,
    VyperException,
)


def validate_functions(vy_module):

    """Analyzes a vyper ast and validates the function-level namespaces."""

    err_list = ExceptionList()
    for node in vy_module.get_children(vy_ast.FunctionDef):
        with namespace.enter_scope():
            try:
                FunctionNodeVisitor(node)
            except VyperException as e:
                err_list.append(e)

    err_list.raise_if_not_empty()


def _is_terminus_node(node):
    if getattr(node, '_is_terminus', None):
        return True
    if isinstance(node, vy_ast.Expr) and isinstance(node.value, vy_ast.Call):
        func = get_definition_from_node(node.value.func)
        if getattr(func, '_is_terminus', None):
            return True
    return False


def check_for_terminus(node_list: list) -> bool:
    if next((i for i in node_list if _is_terminus_node(i)), None):
        return True
    for node in [i for i in node_list if isinstance(i, vy_ast.If)][::-1]:
        if not node.orelse or not check_for_terminus(node.orelse):
            continue
        if not check_for_terminus(node.body):
            continue
        return True
    return False


# TODO constancy checks could be handled here. if the function being evaluated
# is_constant, check that the target of all Call nodes is also constant
class FunctionNodeVisitor(VyperNodeVisitorBase):

    ignored_types = (
        vy_ast.Break,
        vy_ast.Constant,
        vy_ast.Continue,
        vy_ast.Pass,
    )
    scope_name = "function"

    def __init__(self, fn_node):
        self.fn_node = fn_node
        self.func = namespace["self"].get_member(fn_node)
        namespace.update(self.func.arguments)
        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type:
            if not check_for_terminus(fn_node.body):
                raise FunctionDeclarationException(
                    f"Missing or unmatched return statements in function '{fn_node.name}'", fn_node
                )

    def visit_AnnAssign(self, node):
        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )
        name = node.target.id
        if name in namespace["self"].members:
            raise NamespaceCollision(
                "Variable name shadows an existing storage-scoped value", node
            )
        var = get_variable_from_nodes(name, node.annotation, node.value)
        try:
            namespace[name] = var
        except VyperException as exc:
            raise exc.with_annotation(node)

    def visit_Assign(self, node):
        target = get_definition_from_node(node.target)
        target.validate_modification(node)

    def visit_AugAssign(self, node):
        target = get_definition_from_node(node.target)
        target.validate_modification(node)

    def visit_Raise(self, node):
        if not node.exc:
            raise StructureException("Raise must have a reason", node)
        if not isinstance(node.exc, vy_ast.Str) or len(node.exc.value) > 32:
            raise InvalidType("Reason must be a string of 32 characters or less", node.exc)

    def visit_Assert(self, node):
        if node.msg:
            if not (
                (isinstance(node.msg, vy_ast.Name) and node.msg.id == "UNREACHABLE") or
                isinstance(node.msg, vy_ast.Str)
            ):
                raise InvalidType("Reason must UNREACHABLE or a string literal", node.msg)

        if isinstance(node.test, (vy_ast.BoolOp, vy_ast.Compare)):
            get_definition_from_node(node.test)
        elif not is_subtype(get_definition_from_node(node.test).type, BoolBase):
            raise InvalidType("Assertion test value must be a boolean", node.test)

    def visit_Return(self, node):
        values = node.value
        if values is None:
            if self.func.return_type:
                raise FunctionDeclarationException("Return statement is missing a value", node)
            return
        if values and self.func.return_type is None:
            raise FunctionDeclarationException("Function does not return any values", node)
        compare_types(self.func.return_type, get_definition_from_node(values).type, node)

    def visit_UnaryOp(self, node):
        get_definition_from_node(node)

    def visit_BinOp(self, node):
        get_definition_from_node(node)

    def visit_Compare(self, node):
        get_definition_from_node(node)

    def visit_Call(self, node):
        value = get_definition_from_node(node.func)
        value.fetch_call_return(node)

    def visit_If(self, node):
        test = get_definition_from_node(node.test)
        if not is_subtype(test.type, BoolBase):
            raise StructureException("If test condition must be a boolean", node.test)
        with namespace.enter_scope():
            for n in node.body:
                self.visit(n)
        with namespace.enter_scope():
            for n in node.orelse:
                self.visit(n)

    def visit_For(self, node):
        # TODO For needs a detailed spec, some of the limitations here seem inconsistent

        with namespace.enter_scope():

            # iteration via range()
            if isinstance(node.iter, vy_ast.Call):
                if node.iter.func.id != "range":
                    raise ConstancyViolation(
                        "Cannot iterate over the result of a function call", node.iter
                    )
                validate_call_args(node.iter, (1, 2))

                args = node.iter.args
                target_type = get_definition_from_node(args[0]).type
                if len(args) == 1:
                    # range(10)
                    get_literal_or_raise(args[0])

                else:
                    first_var = get_definition_from_node(args[0])
                    print(type(first_var))
                    if not is_subtype(first_var.type, IntegerBase):
                        raise InvalidType("Value is not an integer", args[0])
                    if isinstance(first_var, Reference):

                        if (
                            not isinstance(args[1], vy_ast.BinOp) or
                            not isinstance(args[1].op, vy_ast.Add)
                        ):
                            raise StructureException(
                                "Second element must be the first element plus a literal value",
                                args[0]
                            )
                        if not vy_ast.compare_nodes(args[0], args[1].left):
                            raise StructureException(
                                "First and second variable must be the same", args[1].left
                            )
                        if not isinstance(args[1].right, vy_ast.Int):
                            raise InvalidLiteral("Literal must be an integer", args[1].right)
                    else:
                        second_var = get_definition_from_node(args[1])
                        if not isinstance(second_var, Literal):
                            raise InvalidType("Value must be a literal integer", args[1])
                        if not is_subtype(second_var.type, IntegerBase):
                            raise InvalidType("Value must be an integer", args[1])
                        if first_var.value >= second_var.value:
                            raise InvalidLiteral("Second value must be > first value", args[1])

            else:
                # iteration over a variable or literal list
                iter_var = get_definition_from_node(node.iter)
                if not isinstance(iter_var.type, list):
                    raise InvalidType("Value is not iterable", node.iter)
                target_type = iter_var.type[0]

            var = Reference.from_type(target_type, node.target.id)
            try:
                namespace[node.target.id] = var
            except VyperException as exc:
                raise exc.with_annotation(node)

            for n in node.body:
                self.visit(n)

    def visit_Expr(self, node):
        # TODO some types of Expr should raise
        self.visit(node.value)

    def visit_Attribute(self, node):
        get_definition_from_node(node)

    def visit_Name(self, node):
        get_definition_from_node(node)

    def visit_Subscript(self, node):
        get_definition_from_node(node)

    def visit_List(self, node):
        get_definition_from_node(node)
