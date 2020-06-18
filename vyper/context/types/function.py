from collections import OrderedDict
from typing import Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context import namespace
from vyper.context.types.bases import BaseType
from vyper.context.types.indexable.sequence import TupleType
from vyper.context.types.utils import (
    build_type_from_ann_assign,
    get_type_from_abi,
    get_type_from_annotation,
)
from vyper.context.types.value.numeric import Uint256Type
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    ConstancyViolation,
    FunctionDeclarationException,
    InvalidType,
    NamespaceCollision,
    NonPayableViolation,
    StructureException,
)


class ContractFunctionType(BaseType):
    """
    Contract function type.

    Functions compare false against all types and so cannot be cast without
    being called. Calls are validated by `fetch_call_return`, check the call
    arguments against `arguments`, and return `return_type`.

    Attributes
    ----------
    name : str
        The name of the function.
    arguments : OrderedDict
        Function input arguments as {'name': BaseType}
    arg_count : Tuple[int, int] | int
        The number of input arguments. If given as a tuple, the value represents
        (min, max) when default values are given.
    kwarg_keys : List
        List of optional input argument keys.
    is_public : bool
        Boolean indicating if the function is public.
    is_payable : bool
        Boolean indicating if the function is payable.
    is_constant : bool
        Boolean indicating if the function is constant.
    nonreentrant : str
        Re-entrancy lock name.
    """

    _is_callable = True

    def __init__(
        self,
        name: str,
        arguments: OrderedDict,
        arg_count: Union[Tuple[int, int], int],
        return_type,
        is_public: bool = False,
        is_payable: bool = False,
        is_constant: bool = False,
        nonreentrant: str = False,
    ) -> None:
        self.name = name
        self.arguments = arguments
        self.arg_count = arg_count
        self.return_type = return_type
        self.kwarg_keys = []
        if isinstance(arg_count, tuple):
            self.kwarg_keys = list(self.arguments)[self.arg_count[0]:]
        self.is_public = is_public
        self.is_payable = is_payable
        self.is_constant = is_constant
        self.nonreentrant = nonreentrant

    def __repr__(self):
        return f"contract function '{self.name}'"

    @classmethod
    def from_abi(cls, abi: dict):
        """
        Generate a `ContractFunctionType` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing a function.

        Returns
        -------
        ContractFunction object.
        """

        kwargs = {f"is_{i}": True for i in ("constant", "payable") if abi[i]}
        arguments = OrderedDict()
        for item in abi["inputs"]:
            arguments[item["name"]] = get_type_from_abi(item, True)
        return_type = None
        if len(abi["outputs"]) == 1:
            return_type = get_type_from_abi(abi["outputs"][0], True)
        elif len(abi["outputs"]) > 1:
            return_type = tuple(get_type_from_abi(i, True) for i in abi["outputs"])
        return cls(abi["name"], arguments, len(arguments), return_type, "public", **kwargs)

    @classmethod
    def from_FunctionDef(
        cls,
        node: vy_ast.FunctionDef,
        is_public: Optional[bool] = None,
        include_defaults: Optional[bool] = True,
    ) -> "ContractFunctionType":
        """
        Generate a `ContractFunctionType` object from a `FunctionDef` node.

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
        ContractFunctionType
        """
        kwargs = {}
        if is_public is not None:
            kwargs["is_public"] = is_public

        # decorators
        for decorator in node.decorator_list:

            if isinstance(decorator, vy_ast.Call):
                if decorator.get("func.id") != "nonreentrant":
                    raise StructureException("Decorator is not callable", decorator)
                if len(decorator.args) != 1 or not isinstance(decorator.args[0], vy_ast.Str):
                    raise StructureException(
                        "@nonreentrant name must be given as a single string literal", decorator,
                    )
                kwargs["nonreentrant"] = decorator.args[0].value

            elif isinstance(decorator, vy_ast.Name):
                value = decorator.id
                if value in ("public", "private"):
                    if "is_public" in kwargs:
                        raise FunctionDeclarationException(
                            "Visibility must be public or private, not both", node
                        )
                    kwargs["is_public"] = value == "public"
                elif value in ("constant", "payable"):
                    kwargs[f"is_{value}"] = True
                else:
                    raise FunctionDeclarationException(f"Unknown decorator: {value}", decorator)

            else:
                raise StructureException("Bad decorator syntax", decorator)

        if "is_public" not in kwargs:
            raise FunctionDeclarationException("Visibility must be public or private", node)

        # call arguments
        arg_count = len(node.args.args)
        if node.args.defaults:
            arg_count = (arg_count - len(node.args.defaults), arg_count)

        arguments = OrderedDict()
        if include_defaults:
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + node.args.defaults
        else:
            defaults = [None] * len(node.args.args)

        for arg, value in zip(node.args.args, defaults):
            if arg.arg in ("gas", "value"):
                raise ArgumentException(
                    f"Cannot use '{arg.arg}' as a variable name in a function input", arg,
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
                if value.get("value.id") == "msg":
                    if value.attr == "sender" and not kwargs["is_public"]:
                        raise ConstancyViolation(
                            "msg.sender is not allowed in private functions", value
                        )
                    if value.attr == "value" and not kwargs.get("is_payable"):
                        raise NonPayableViolation(
                            "msg.value is not allowed in non-payable functions", value
                        )

            arguments[arg.arg] = build_type_from_ann_assign(arg.annotation, value, is_constant=True)

        # return types
        if node.returns is None:
            return_type = None
        elif isinstance(node.returns, (vy_ast.Name, vy_ast.Call, vy_ast.Subscript)):
            return_type = get_type_from_annotation(node.returns)
        elif isinstance(node.returns, vy_ast.Tuple):
            return_type = ()
            for n in node.returns.elements:
                return_type += (get_type_from_annotation(n),)
            return_type = TupleType(return_type)
        else:
            raise InvalidType("Function return value must be a type name or tuple", node.returns)

        return cls(node.name, arguments, arg_count, return_type, **kwargs)

    @classmethod
    def from_AnnAssign(cls, node: vy_ast.AnnAssign) -> "ContractFunctionType":
        """
        Generate a `ContractFunctionType` object from an `AnnAssign` node.

        Used to create function definitions for public variables.

        Arguments
        ---------
        node : AnnAssign
            Vyper ast node to generate the function definition from.

        Returns
        -------
        ContractFunctionType
        """
        type_ = get_type_from_annotation(node.annotation.args[0])
        arguments, return_type = type_.get_signature()
        return cls(node.target.id, arguments, len(arguments), return_type, is_public=True)

    def get_signature(self):
        return list(self.arguments.values()), self.return_type

    def fetch_call_return(self, node: vy_ast.Call):
        if node.get("func.value.id") == "self" and self.is_public:
            raise CallViolation("Cannnot call public functions via 'self'", node)

        # for external calls, include gas and value as optional kwargs
        kwarg_keys = self.kwarg_keys.copy()
        if node.get("func.value.id") != "self":
            kwarg_keys += ["gas", "value"]
        validate_call_args(node, self.arg_count, kwarg_keys)

        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)

        for kwarg in node.keywords:
            if kwarg.arg in ("gas", "value"):
                validate_expected_type(kwarg.value, Uint256Type())
            else:
                validate_expected_type(kwarg.arg, kwarg.value)

        return self.return_type
