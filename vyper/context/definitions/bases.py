from vyper import (
    ast as vy_ast,
)
from vyper.context.types import (
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

    __slots__ = ("return_var", "arguments", "arg_count")

    def __init__(
        self,
        namespace,
        name: str,
        enclosing_scope: str,
        arguments,  # OrderedDict that can hold variables or types
        arg_count,
        return_var,
    ):
        BaseDefinition.__init__(self, namespace, name, enclosing_scope)
        self.arguments = arguments
        self.arg_count = arg_count
        self.return_var = return_var

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, self.arg_count)
        for arg, key in zip(node.args, self.arguments):
            given_type = get_type_from_node(self.namespace, arg)
            if hasattr(self.arguments[key], 'type'):
                expected_type = self.arguments[key].type
            else:
                expected_type = self.arguments[key]
            # TODO better exception, give the name of the argument
            compare_types(expected_type, given_type, arg)
        return self.return_var
