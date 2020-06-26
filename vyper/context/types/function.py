import warnings
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.bases import BaseTypeDefinition, DataLocation
from vyper.context.types.indexable.sequence import TupleDefinition
from vyper.context.types.utils import (
    StringEnum,
    check_constant,
    get_type_from_abi,
    get_type_from_annotation,
)
from vyper.context.types.value.numeric import Uint256Definition
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    CompilerPanic,
    ConstancyViolation,
    FunctionDeclarationException,
    InvalidType,
    NamespaceCollision,
    StructureException,
)


class FunctionVisibility(StringEnum):
    PUBLIC = StringEnum.auto()
    PRIVATE = StringEnum.auto()


class StateMutability(StringEnum):
    PURE = StringEnum.auto()
    VIEW = StringEnum.auto()
    NONPAYABLE = StringEnum.auto()
    PAYABLE = StringEnum.auto()

    @classmethod
    def from_abi(cls, abi_dict) -> "StateMutability":
        """
        Extract stateMutability from an entry in a contract's ABI
        """
        if "stateMutability" in abi_dict:
            return cls(abi_dict["stateMutability"])
        elif "payable" in abi_dict and abi_dict["payable"]:
            return StateMutability.PAYABLE
        elif "constant" in abi_dict and abi_dict["constant"]:
            return StateMutability.VIEW
        else:  # Assume nonpayable if neither field is there, or constant/payable not set
            return StateMutability.NONPAYABLE


class ContractFunctionType(BaseTypeDefinition):
    """
    Contract function type.

    Functions compare false against all types and so cannot be assigned without
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
        return_type: Optional[BaseTypeDefinition],
        is_public: bool,
        is_payable: bool = False,
        is_constant: bool = False,
        nonreentrant: Optional[str] = None,
    ) -> None:
        super().__init__(DataLocation.UNSET, is_constant, is_public)
        self.name = name
        self.arguments = arguments
        self.arg_count = arg_count
        self.return_type = return_type
        self.kwarg_keys = []
        if isinstance(arg_count, tuple):
            self.kwarg_keys = list(self.arguments)[arg_count[0] :]  # noqa: E203
        self.is_payable = is_payable
        self.nonreentrant = nonreentrant

    def __repr__(self):
        return f"contract function '{self.name}'"

    @classmethod
    def from_abi(cls, abi: Dict) -> "ContractFunctionType":
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

        # Handle either constant/payable fields in ABI, or...
        kwargs: Dict[str, Any] = {
            f"is_{i}": True for i in ("constant", "payable") if i in abi and abi[i]
        }
        # stateMutability field (takes precedence)
        if "stateMutability" in abi:
            if abi["stateMutability"] == "payable":
                kwargs["is_payable"] = True
                kwargs["is_constant"] = False
            elif abi["stateMutability"] == "view" or abi["stateMutability"] == "pure":
                kwargs["is_payable"] = False
                kwargs["is_constant"] = True
        # NOTE: The state mutability nonpayable is reflected in Solidity by not
        #       specifying a state mutability modifier at all. Do the same here.
        arguments = OrderedDict()
        for item in abi["inputs"]:
            arguments[item["name"]] = get_type_from_abi(
                item, location=DataLocation.CALLDATA, is_constant=True
            )
        return_type = None
        if len(abi["outputs"]) == 1:
            return_type = get_type_from_abi(
                abi["outputs"][0], location=DataLocation.CALLDATA, is_constant=True
            )
        elif len(abi["outputs"]) > 1:
            return_type = TupleDefinition(
                tuple(
                    get_type_from_abi(i, location=DataLocation.CALLDATA, is_constant=True)
                    for i in abi["outputs"]
                )
            )
        return cls(abi["name"], arguments, len(arguments), return_type, is_public=True, **kwargs,)

    @classmethod
    def from_FunctionDef(
        cls,
        node: vy_ast.FunctionDef,
        is_constant: Optional[bool] = None,
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
        kwargs: Dict[str, Any] = {}
        if is_constant is not None:
            kwargs["is_constant"] = is_constant
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
                if decorator.id in ("public", "private"):
                    if "is_public" in kwargs:
                        raise FunctionDeclarationException(
                            "Visibility must be public or private, not both", node
                        )
                    kwargs["is_public"] = bool(decorator.id == "public")
                elif decorator.id == "payable":
                    kwargs["is_payable"] = True
                elif decorator.id == "view":
                    kwargs["is_constant"] = True
                else:
                    if decorator.id == "constant":
                        warnings.warn(
                            "'@constant' decorator has been removed (see VIP2040). "
                            "Use `@view` instead.",
                            DeprecationWarning,
                        )
                    raise FunctionDeclarationException(
                        f"Unknown decorator: {decorator.id}", decorator
                    )

            else:
                raise StructureException("Bad decorator syntax", decorator)

        if "is_public" not in kwargs:
            raise FunctionDeclarationException("Visibility must be public or private", node)

        # call arguments
        arg_count: Union[Tuple[int, int], int] = len(node.args.args)
        if node.args.defaults:
            arg_count = (
                len(node.args.args) - len(node.args.defaults),
                len(node.args.args),
            )

        arguments = OrderedDict()
        if include_defaults:
            defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + node.args.defaults
        else:
            defaults = [None] * len(node.args.args)

        namespace = get_namespace()
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

            type_definition = get_type_from_annotation(
                arg.annotation, location=DataLocation.CALLDATA, is_constant=True
            )
            if value is not None:
                if not check_constant(value):
                    raise ConstancyViolation("Value must be literal or environment variable", value)
                validate_expected_type(value, type_definition)

            arguments[arg.arg] = type_definition

        # return types
        if node.returns is None:
            return_type = None
        elif isinstance(node.returns, (vy_ast.Name, vy_ast.Call, vy_ast.Subscript)):
            return_type = get_type_from_annotation(node.returns, location=DataLocation.MEMORY)
        elif isinstance(node.returns, vy_ast.Tuple):
            tuple_types: Tuple = ()
            for n in node.returns.elements:
                tuple_types += (get_type_from_annotation(n, location=DataLocation.MEMORY),)
            return_type = TupleDefinition(tuple_types)
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
        if not isinstance(node.annotation, vy_ast.Call):
            raise CompilerPanic("Annotation must be a call to public()")
        type_ = get_type_from_annotation(node.annotation.args[0], location=DataLocation.STORAGE)
        arguments, return_type = type_.get_signature()
        args_dict: OrderedDict = OrderedDict()
        for item in arguments:
            args_dict[f"arg{len(args_dict)}"] = item
        return cls(node.target.id, args_dict, len(arguments), return_type, is_public=True)

    def get_signature(self) -> Tuple[Tuple, Optional[BaseTypeDefinition]]:
        return tuple(self.arguments.values()), self.return_type

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[BaseTypeDefinition]:
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
                validate_expected_type(kwarg.value, Uint256Definition())
            else:
                validate_expected_type(kwarg.arg, kwarg.value)

        return self.return_type
