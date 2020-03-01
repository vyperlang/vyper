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

    __slots__ = ("namespace", "name")

    def __init__(self, namespace, name):
        self.namespace = namespace
        self.name = name


class FunctionDefinition(BaseDefinition):

    __slots__ = ("return_var", "arguments", "arg_count", "kwarg_keys")

    def __init__(
        self,
        namespace,
        name: str,
        arguments,  # OrderedDict that can hold variables or types
        arg_count,
        return_var,
    ):
        BaseDefinition.__init__(self, namespace, name)
        self.arguments = arguments
        self.arg_count = arg_count
        self.return_var = return_var
        self.kwarg_keys = None
        if isinstance(arg_count, tuple):
            self.kwarg_keys = list(self.arguments)[self.arg_count[0]:]

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, self.arg_count, self.kwarg_keys)
        for arg, key in zip(node.args, self.arguments):
            self._compare_argument(key, arg)
        for kwarg in node.keywords:
            self._compare_argument(kwarg.arg, kwarg.value)
        return self.return_var

    def _compare_argument(self, key, arg_node):
        given_type = get_type_from_node(self.namespace, arg_node)
        if hasattr(self.arguments[key], 'type'):
            expected_type = self.arguments[key].type
        else:
            expected_type = self.arguments[key]
        # TODO better exception, give the name of the argument
        compare_types(given_type, expected_type, arg_node)
