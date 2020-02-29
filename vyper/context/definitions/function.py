from collections import (
    OrderedDict,
)
from typing import (
    Optional,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.definitions.bases import (
    FunctionDefinition,
)
from vyper.context.definitions.variable import (
    Variable,
    get_variable_from_nodes,
)
from vyper.context.types import (
    compare_types,
    get_type_from_annotation,
)
from vyper.exceptions import (
    StructureException,
)


def get_function_from_node(namespace, node: vy_ast.FunctionDef, visibility: Optional[str] = None):
    # decorators
    kwargs = {}
    decorators = [i.id for i in node.decorator_list]
    for value in decorators:
        if value in ("public", "private"):
            if visibility:
                raise StructureException("Visibility must be public or private, not both", node)
            visibility = value
        else:
            kwargs[f"is_{value}"] = True
    if not visibility:
        raise StructureException("Function visibility must be public or private", node)

    # call arguments
    arg_count = len(node.args.args)
    if node.args.defaults:
        arg_count = (arg_count-len(node.args.defaults), arg_count)

    arguments = OrderedDict()
    defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + node.args.defaults
    for arg, value in zip(node.args.args, defaults):
        if arg.arg in namespace or arg.arg in arguments:
            raise StructureException("Namespace collision", arg)
        var = get_variable_from_nodes(namespace, arg.arg, arg.annotation, value)
        arguments[arg.arg] = var

    # return types
    if node.returns is None:
        return_var = None
    elif isinstance(node.returns, vy_ast.Name):
        return_type = get_type_from_annotation(namespace, node.returns)
        return_var = Variable(namespace, "", return_type)
    elif isinstance(node.returns, vy_ast.Tuple):
        return_type = ()
        for n in node.returns.elts:
            return_type += (get_type_from_annotation(namespace, n),)
        return_var = Variable(namespace, "", return_type)
    else:
        raise StructureException(
            f"Function return value must be a type name or tuple", node.returns
        )

    return ContractFunction(
        namespace, node.name, arguments, arg_count, return_var, visibility, **kwargs
    )


class ContractFunction(FunctionDefinition):
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
    __slots__ = ("visibility", "is_constant", "is_payable")

    def __init__(
        self,
        namespace,
        name: str,
        arguments,
        arg_count,
        return_var,
        visibility,
        **kwargs,
    ):
        super().__init__(namespace, name, arguments, arg_count, return_var)
        self.visibility = visibility
        for key, value in kwargs.items():
            setattr(self, f'is_{key}', value)

    def __eq__(self, other):
        if not (  # NOQA: E721
            isinstance(other, ContractFunction) and
            self.name == other.name and
            self.visibility == other.visibility and
            type(self.return_var) is type(other.return_var) and
            list(self.arguments) == list(other.arguments)
        ):
            return False
        if self.return_var:
            try:
                compare_types(self.return_var.type, other.return_var.type, None)
            except Exception:
                return False
        for key in self.arguments:
            try:
                compare_types(self.arguments[key].type, other.arguments[key].type, None)
            except Exception:
                return False
        return True

    def validate_call(self, node: vy_ast.Call):
        if node.get('func.value.id') == "self" and self.visibility == "public":
            raise StructureException("Can only call from public function to private function", node)
        # TODO keywords?
        return super().validate_call(node)
