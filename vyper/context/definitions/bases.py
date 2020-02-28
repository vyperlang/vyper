from vyper import (
    ast as vy_ast,
)
from vyper.context.typecheck import (
    compare_types,
    get_type_from_node,
)
from vyper.context.utils import (
    check_call_args,
)


class BaseDefinition:

    __slots__ = ("namespace", "name", "enclosing_scope")

    def __init__(self, namespace, name, enclosing_scope):
        self.namespace = namespace
        self.name = name
        self.enclosing_scope = enclosing_scope


class FunctionDefinition(BaseDefinition):

    __slots__ = ("return_type", "arguments", "arg_count")

    def __init__(
        self,
        namespace,
        name: str,
        enclosing_scope: str,
        arguments,
        arg_count,
        return_type,
    ):
        super().__init__(namespace, name, enclosing_scope)
        self.arguments = arguments
        self.arg_count = arg_count
        self.return_type = return_type

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, self.arg_count)
        for arg, key in zip(node.args, self.arguments):
            typ = get_type_from_node(self.namespace, arg)
            compare_types(self.arguments[key].type, typ, arg)
        return self.return_type
