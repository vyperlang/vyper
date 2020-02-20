from collections import OrderedDict
from vyper import ast as vy_ast
from vyper.context.datatypes.variables import (
    Variable,
)
from vyper.context.utils import get_leftmost_id
from vyper.exceptions import (
    StructureException,
)


class Function:

    # TODO @nonreentrant
    __slots__ = (
        "namespace",
        "node",
        "name",
        "address",
        "visibility",
        "is_constant",
        "is_payable",
        "return_types",
        "arguments",
    )
    _id = "def"

    def __init__(self, namespace, node):
        self.namespace = namespace
        self.node = node
        self.name = node.name

    def _introspect(self):
        self._introspect_decorators(self.node.decorator_list)
        self._introspect_call_args(self.node.args)
        self._introspect_return_types(self.node.returns)

    def _introspect_decorators(self, decorator_list):
        decorators = [i.id for i in decorator_list]
        if all(i in decorators for i in ("public", "private")):
            raise StructureException(
                "Visibility must be public or private, not both", self.node
            )
        for value in decorators:
            if value in ("public", "private"):
                self.visibility = value
            else:
                setattr(self, f"is_{value}", True)
        if not hasattr(self, "visibility"):
            raise StructureException(
                "Function visibility must be public or private", self.node
            )

    def _introspect_call_args(self, node: vy_ast.arguments):
        self.arguments = OrderedDict()
        arguments = node.args.copy()
        defaults = [None] * (len(arguments) - len(node.defaults)) + node.defaults
        for arg, value in zip(arguments, defaults):
            if arg.arg in self.namespace or arg.arg in self.arguments:
                raise StructureException("Namespace collision", arg)
            var = Variable(self.namespace, arg.arg, arg.annotation, value)
            var._introspect()
            self.arguments[arg.arg] = var

    def _introspect_return_types(self, node):
        self.return_types = ()
        if node is None:
            return
        if isinstance(node, vy_ast.Name):
            return_types = (node,)
        elif isinstance(node, vy_ast.Tuple):
            return_types = node.elts
        else:
            raise StructureException(
                f"Function return value must be a type name or tuple", node
            )
        for node in return_types:
            id_ = get_leftmost_id(node)
            self.return_types += (self.namespace[id_].get_type(node),)
