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
    CallableDefinition,
    PublicDefinition,
    ReadOnlyDefinition,
)
from vyper.context.definitions.utils import (
    get_definition_from_node,
)
from vyper.context.definitions.values import (
    Reference,
    build_value_definition,
)
from vyper.context.types import (
    get_builtin_type,
    get_type_from_annotation,
)
from vyper.context.utils import (
    compare_types,
    validate_call_args,
)
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    ConstancyViolation,
    FunctionDeclarationException,
    InvalidType,
    NamespaceCollision,
    StructureException,
)


class ContractFunction(CallableDefinition, PublicDefinition):
    """
    A contract function definition.

    Function definitions differ from value definitions in that they have no `type`
    member. Instead, functions implement `fetch_call_return`, check the call
    arguments against `arguments`, and return `return_type`.

    Attributes
    ----------
    is_public : bool
        Boolean indicating if the function is public.
    is_payable : bool
        Boolean indicating if the function is payable.
    is_constant : bool
        Boolean indicating if the function is constant.
    nonreentrant : str
        Re-entrancy lock name
    """

    def __init__(
        self,
        name: str,
        arguments: OrderedDict,
        arg_count: Union[Tuple[int, int], int],
        return_type,
        is_public=False,
        is_payable=False,
        is_constant=False,
        nonreentrant: str = False,
    ):
        super().__init__(name, arguments, arg_count, return_type)
        self.is_public = is_public
        self.is_payable = is_payable
        self.is_constant = is_constant
        self.nonreentrant = nonreentrant

    @classmethod
    def from_abi(cls, abi: dict) -> "ContractFunction":
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
            arguments[item['name']] = Reference.from_type(get_builtin_type(item), item['name'])
        return_type = None
        if len(abi['outputs']) == 1:
            return_type = get_builtin_type(abi['outputs'][0])
        elif len(abi['outputs']) > 1:
            return_type = tuple(get_builtin_type(abi['outputs']))
        return cls(abi['name'], arguments, len(arguments), return_type, "public", **kwargs)

    @classmethod
    def from_FunctionDef(
        cls,
        node: vy_ast.FunctionDef,
        is_public: Optional[bool] = None,
        include_defaults: Optional[bool] = True,
    ):
        """
        Generates a ContractFunction object from an ast node.

        Arguments
        ---------
        node : FunctionDef
            Vyper ast node to generate the function definition from.
        is_public : bool, optional
            Boolean indicating if the function is public or private. Should only be
            given if the visibility not is indicated via a decorator.
        include_defaults: bool, optional
            If False, default arguments are ignored when parsing generating the
            object. Used for interfaces.

        Returns
        -------
        ContractFunction object.
        """
        kwargs = {}
        if is_public is not None:
            kwargs['is_public'] = is_public

        # decorators
        for decorator in node.decorator_list:
            if isinstance(decorator, vy_ast.Call):
                if decorator.get('func.id') != "nonreentrant":
                    raise StructureException("Decorator is not callable", decorator)
                if len(decorator.args) != 1 or not isinstance(decorator.args[0], vy_ast.Str):
                    raise StructureException(
                        "@nonreentrant name must be given as a single string literal", decorator
                    )
                kwargs['nonreentrant'] = decorator.args[0].value
            elif isinstance(decorator, vy_ast.Name):
                value = decorator.id
                if value in ("public", "private"):
                    if 'is_public' in kwargs:
                        raise FunctionDeclarationException(
                            "Visibility must be public or private, not both", node
                        )
                    kwargs['is_public'] = value == "public"
                elif value in ("constant", "payable"):
                    kwargs[f"is_{value}"] = True
                else:
                    raise FunctionDeclarationException(f"Unknown decorator: {value}", decorator)
            else:
                raise StructureException("Bad decorator syntax", decorator)
        if 'is_public' not in kwargs:
            raise FunctionDeclarationException("Visibility must be public or private", node)

        # call arguments
        arg_count = len(node.args.args)
        if node.args.defaults:
            arg_count = (arg_count-len(node.args.defaults), arg_count)

        arguments = OrderedDict()
        if include_defaults:
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + node.args.defaults
        else:
            defaults = [None] * len(node.args.args)
        for arg, value in zip(node.args.args, defaults):
            if arg.arg in ("gas", "value"):
                raise ArgumentException(
                    f"Cannot use '{arg.arg}' as a variable name in a function input", arg
                )
            if arg.arg in arguments:
                raise ArgumentException(f"Function contains multiple inputs named {arg.arg}", arg)
            if arg.arg in namespace["self"].members:
                raise NamespaceCollision("Name shadows an existing storage-scoped value", arg)
            if arg.arg in namespace:
                raise NamespaceCollision(arg.arg, arg)

            if arg.annotation is None:
                raise ArgumentException(f"Function argument '{arg.arg}' is missing a type", arg)

            if value is not None:
                if not isinstance(get_definition_from_node(value), ReadOnlyDefinition):
                    raise ConstancyViolation("Must be a literal or constant", value)

            var = build_value_definition(arg.arg, arg.annotation, value)
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

        return cls(node.name, arguments, arg_count, return_type, **kwargs)

    @classmethod
    def from_AnnAssign(cls, node):
        var = build_value_definition(node.target.id, node.annotation, None)
        arguments, return_type = var.get_signature()
        return cls(var.name, arguments, len(arguments), return_type, is_public=True)

    def get_signature(self):
        return [i.type for i in self.arguments.values()], self.return_type

    def fetch_call_return(self, node: vy_ast.Call):
        if node.get('func.value.id') == "self" and self.is_public:
            raise CallViolation("Cannnot call public functions via 'self'", node)

        # for external calls, add gas and value as optional kwargs
        kwarg_keys = self.kwarg_keys.copy()
        if node.get('func.value.id') != "self":
            kwarg_keys += ['gas', 'value']
        validate_call_args(node, self.arg_count, kwarg_keys)

        for arg, key in zip(node.args, self.arguments):
            self._compare_argument(key, arg)

        for kwarg in node.keywords:
            if kwarg.arg in ("gas", "value"):
                given_type = get_definition_from_node(kwarg.value).type
                expected_type = get_builtin_type("uint256")
                compare_types(expected_type, given_type, kwarg)
            else:
                self._compare_argument(kwarg.arg, kwarg.value)

        return Reference.from_type(self.return_type, "return value")
