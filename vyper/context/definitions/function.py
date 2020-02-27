from collections import (
    OrderedDict,
)
from typing import (
    Optional,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.variable import (
    get_variable_from_nodes,
)
from vyper.context.typecheck import (
    compare_types,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    StructureException,
)


class Function:
    """
    TODO

    Attributes
    ----------
    arguments : OrderedDict
        An ordered dict of call arguments for the function.
    return_type
        A type object, or tuple of type objects, representing return types for
        the function.
    """
    # TODO @nonreentrant
    __slots__ = (
        "namespace",
        "node",
        "name",
        "visibility",
        "is_constant",
        "is_payable",
        "return_type",
        "arguments",
        "arg_count",
    )

    def __init__(self, namespace, node: vy_ast.FunctionDef, visibility: Optional[str] = None):
        self.namespace = namespace.copy('module')
        self.namespace.add_scope(node.name, 'module')
        self.node = node
        self.name = node.name
        if visibility is not None:
            self.visibility = visibility
        self._inspect_decorators(self.node.decorator_list)
        self._inspect_call_args(self.node.args)
        self._inspect_return_type(self.node.returns)

    def _inspect_decorators(self, decorator_list):
        decorators = [i.id for i in decorator_list]
        for value in decorators:
            if value in ("public", "private"):
                if hasattr(self, "visibility"):
                    raise StructureException(
                        "Visibility must be public or private, not both", self.node
                    )
                self.visibility = value
            else:
                setattr(self, f"is_{value}", True)
        if not hasattr(self, "visibility"):
            raise StructureException(
                "Function visibility must be public or private", self.node
            )

    def _inspect_call_args(self, node: vy_ast.arguments):
        self.arg_count = len(node.args)
        if node.defaults:
            self.arg_count = (self.arg_count-len(node.defaults), self.arg_count)

        self.arguments = OrderedDict()
        arguments = node.args.copy()
        defaults = [None] * (len(arguments) - len(node.defaults)) + node.defaults
        for arg, value in zip(arguments, defaults):
            if arg.arg in self.namespace or arg.arg in self.arguments:
                raise StructureException("Namespace collision", arg)
            var = get_variable_from_nodes(self.namespace, arg.arg, arg.annotation, value)
            self.arguments[arg.arg] = var
        self.namespace.update(self.arguments)

    def _inspect_return_type(self, node):
        if node is None:
            self.return_type = None
        elif isinstance(node, vy_ast.Name):
            self.return_type = get_type_from_annotation(self.namespace, node)
        elif isinstance(node, vy_ast.Tuple):
            self.return_type = ()
            for n in node.elts:
                self.return_type += (get_type_from_annotation(self.namespace, n),)
        else:
            raise StructureException(
                f"Function return value must be a type name or tuple", node
            )

    @property
    def enclosing_scope(self):
        return self.node.enclosing_scope

    def __eq__(self, other):
        if not (
            isinstance(other, Function) and
            self.name == other.name and
            self.visibility == other.visibility and
            self.return_type == other.return_type and
            list(self.arguments) == list(other.arguments)
        ):
            return False
        for key in self.arguments:
            if self.arguments[key].type != other.arguments[key].type:
                return False
            if self.arguments[key].value != other.arguments[key].value:
                return False
        return True

    def validate_call(self, node: vy_ast.Call):
        if self.visibility == "public":
            raise StructureException("Can only call from public function to private function", node)
        # TODO keywords?
        check_call_args(node, self.arg_count)
        for arg, key in zip(node.args, self.arguments):
            typ = get_type_from_node(self.namespace, arg)
            compare_types(self.arguments[key].type, typ, arg)
        return self.return_type
