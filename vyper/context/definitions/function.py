from collections import (
    OrderedDict,
)
from typing import (
    Optional,
    Tuple,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions.bases import (
    FunctionDefinition,
)
from vyper.context.definitions.utils import (
    get_definition_from_node,
)
from vyper.context.definitions.variable import (
    Variable,
    get_variable_from_nodes,
)
from vyper.context.types import (
    compare_types,
    get_builtin_type,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.context.utils import (
    validate_call_args,
)
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    FunctionDeclarationException,
    InvalidType,
    NamespaceCollision,
)


def get_function_from_abi(abi: dict):
    """
    Generates a function definition object from an ABI interface.

    Arguments
    ---------
    abi : dict
        An object from a JSON ABI interface, representing a function.

    Returns
    -------
    ContractFunction object.
    """

    kwargs = {f"is_{i}": True for i in ('constant', 'payable') if abi[i]}
    arguments = OrderedDict()
    for item in abi['inputs']:
        arguments[item['name']] = Variable(item['name'], get_builtin_type(item))
    return_type = None
    if len(abi['outputs']) == 1:
        return_type = get_builtin_type(abi['outputs'][0])
    elif len(abi['outputs']) > 1:
        return_type = tuple(get_builtin_type(abi['outputs']))
    return ContractFunction(abi['name'], arguments, len(arguments), return_type, "public", **kwargs)


def get_function_from_node(node: vy_ast.FunctionDef, visibility: Optional[str] = None):
    """
    Generates a function definition object from an ast node.

    Arguments
    ---------
    node : FunctionDef
        Vyper ast node to generate the function definition from.
    visibility : str, optional
        Visibility to apply to the function. If the visibility is specified via
        a decorator, this argument does not need to be provided.

    Returns
    -------
    ContractFunction object.
    """
    # decorators
    kwargs = {}
    decorators = [i.id for i in node.decorator_list]
    for value in decorators:
        if value in ("public", "private"):
            if visibility:
                raise FunctionDeclarationException(
                    "Visibility must be public or private, not both", node
                )
            visibility = value
        else:
            kwargs[f"is_{value}"] = True
    if not visibility:
        raise FunctionDeclarationException("Visibility must be public or private", node)

    # call arguments
    arg_count = len(node.args.args)
    if node.args.defaults:
        arg_count = (arg_count-len(node.args.defaults), arg_count)

    arguments = OrderedDict()
    defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + node.args.defaults
    for arg, value in zip(node.args.args, defaults):
        if arg.arg in ("gas", "value"):
            raise ArgumentException(
                f"Cannot use '{arg.arg}' as a variable name in a function input", arg
            )
        if arg.arg in namespace or arg.arg in arguments:
            raise NamespaceCollision(arg.arg, arg)
        if value is not None:
            if isinstance(get_definition_from_node(value), Variable):
                raise ArgumentException("Must be a literal or constant", value)

        var = get_variable_from_nodes(arg.arg, arg.annotation, value)
        arguments[arg.arg] = var

    # return types
    if node.returns is None:
        return_type = None
    elif isinstance(node.returns, (vy_ast.Name, vy_ast.Call, vy_ast.Subscript)):
        return_type = get_type_from_annotation(node.returns)
    elif isinstance(node.returns, vy_ast.Tuple):
        return_type = ()
        for n in node.returns.elts:
            return_type += (get_type_from_annotation(n),)
    else:
        raise InvalidType(
            f"Function return value must be a type name or tuple", node.returns
        )

    return ContractFunction(node.name, arguments, arg_count, return_type, visibility, **kwargs)


def get_function_from_public_assignment(node):
    var = get_variable_from_nodes(node.target.id, node.annotation, None)
    arguments, return_type = var.get_signature()
    return ContractFunction(var.name, arguments, len(arguments), return_type, "public")


class ContractFunction(FunctionDefinition):
    """
    A contract function definition.

    Function objects differ from variables in that they have no `type` member.
    Instead, functions implement the `get_call_return_type` method, check the call
    arguments against `arguments`, and return `return_type`.

    Attributes
    ----------
    visibility : str
        String indicating the visibility of the function (public or private).
    is_payable : bool
        Boolean indicating if the function is payable.
    is_constant : bool
        Boolean indicating if the function is constant.
    """
    # TODO @nonreentrant
    __slots__ = ("visibility", "is_constant", "is_payable")

    def __init__(
        self,
        name: str,
        arguments: OrderedDict,
        arg_count: Union[Tuple[int, int], int],
        return_type,
        visibility: str,
        **kwargs,
    ):
        super().__init__(name, arguments, arg_count, return_type)
        self.visibility = visibility
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _compare_signature(self, other):
        if not (  # NOQA: E721
            self.name == other.name and
            self.visibility == other.visibility and
            type(self.return_type) is type(other.return_type) and
            len(self.arguments) == len(other.arguments)
        ):
            return False

        try:
            if self.arguments:
                other_args = other.arguments
                if isinstance(other_args, dict):
                    other_args = [i.type for i in other_args.values()]
                compare_types([i.type for i in self.arguments.values()], other_args, None, False)
            if self.return_type:
                compare_types(self.return_type, other.return_type, None, False)
        except Exception:
            return False

        return True

    def get_call_return_type(self, node: vy_ast.Call):
        if node.get('func.value.id') == "self" and self.visibility == "public":
            raise CallViolation("Can only call from public function to private function", node)

        # for external calls, add gas and value as optional kwargs
        kwarg_keys = self.kwarg_keys.copy()
        if node.get('func.value.id') != "self":
            kwarg_keys += ['gas', 'value']
        validate_call_args(node, self.arg_count, kwarg_keys)

        for arg, key in zip(node.args, self.arguments):
            self._compare_argument(key, arg)

        for kwarg in node.keywords:
            if kwarg.arg in ("gas", "value"):
                given_type = get_type_from_node(kwarg.value)
                expected_type = get_builtin_type({"uint256", ("uint256", "wei")})
                compare_types(expected_type, given_type, kwarg)
            else:
                self._compare_argument(kwarg.arg, kwarg.value)

        return self.return_type
