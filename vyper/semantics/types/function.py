import warnings
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    CompilerPanic,
    FunctionDeclarationException,
    InvalidType,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
)
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.bases import (
    BaseTypeDefinition,
    DataLocation,
    StorageSlot,
)
from vyper.semantics.types.indexable.sequence import TupleDefinition
from vyper.semantics.types.user.struct import StructDefinition
from vyper.semantics.types.utils import (
    StringEnum,
    check_constant,
    get_type_from_abi,
    get_type_from_annotation,
)
from vyper.semantics.types.value.numeric import Uint256Definition
from vyper.semantics.validation.utils import validate_expected_type
from vyper.utils import keccak256


class FunctionVisibility(StringEnum):
    EXTERNAL = StringEnum.auto()
    INTERNAL = StringEnum.auto()


class StateMutability(StringEnum):
    PURE = StringEnum.auto()
    VIEW = StringEnum.auto()
    NONPAYABLE = StringEnum.auto()
    PAYABLE = StringEnum.auto()

    @classmethod
    def from_abi(cls, abi_dict: Dict) -> "StateMutability":
        """
        Extract stateMutability from an entry in a contract's ABI
        """
        if "stateMutability" in abi_dict:
            return cls(abi_dict["stateMutability"])
        elif abi_dict.get("payable"):
            return StateMutability.PAYABLE
        elif "constant" in abi_dict and abi_dict["constant"]:
            return StateMutability.VIEW
        else:  # Assume nonpayable if neither field is there, or constant/payable not set
            return StateMutability.NONPAYABLE
        # NOTE: The state mutability nonpayable is reflected in Solidity by not
        #       specifying a state mutability modifier at all. Do the same here.


class ContractFunction(BaseTypeDefinition):
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
    min_arg_count : int
        The minimum number of required input arguments.
    max_arg_count : int
        The maximum number of required input arguments. When a function has no
        default arguments, this value is the same as `min_arg_count`.
    kwarg_keys : List
        List of optional input argument keys.
    function_visibility : FunctionVisibility
        enum indicating the external visibility of a function.
    state_mutability : StateMutability
        enum indicating the authority a function has to mutate it's own state.
    nonreentrant : str
        Re-entrancy lock name.
    """

    _is_callable = True

    def __init__(
        self,
        name: str,
        arguments: OrderedDict,
        min_arg_count: int,
        max_arg_count: int,
        return_type: Optional[BaseTypeDefinition],
        function_visibility: FunctionVisibility,
        state_mutability: StateMutability,
        nonreentrant: Optional[str] = None,
    ) -> None:
        super().__init__(
            # A function definition type only exists while compiling
            DataLocation.UNSET,
            # A function definition type is immutable once created
            is_immutable=True,
            # A function definition type is public if it's visibility is public
            is_public=(function_visibility == FunctionVisibility.EXTERNAL),
        )
        self.name = name
        self.arguments = arguments
        self.min_arg_count = min_arg_count
        self.max_arg_count = max_arg_count
        self.return_type = return_type
        self.kwarg_keys = []
        if min_arg_count < max_arg_count:
            self.kwarg_keys = list(self.arguments)[min_arg_count:]  # noqa: E203
        self.visibility = function_visibility
        self.mutability = state_mutability
        self.nonreentrant = nonreentrant

    def __repr__(self):
        return f"contract function '{self.name}'"

    @classmethod
    def from_abi(cls, abi: Dict) -> "ContractFunction":
        """
        Generate a `ContractFunction` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing a function.

        Returns
        -------
        ContractFunction object.
        """

        arguments = OrderedDict()
        for item in abi["inputs"]:
            arguments[item["name"]] = get_type_from_abi(
                item, location=DataLocation.CALLDATA, is_immutable=True
            )
        return_type = None
        if len(abi["outputs"]) == 1:
            return_type = get_type_from_abi(
                abi["outputs"][0], location=DataLocation.CALLDATA, is_immutable=True
            )
        elif len(abi["outputs"]) > 1:
            return_type = TupleDefinition(
                tuple(
                    get_type_from_abi(i, location=DataLocation.CALLDATA, is_immutable=True)
                    for i in abi["outputs"]
                )
            )
        return cls(
            abi["name"],
            arguments,
            len(arguments),
            len(arguments),
            return_type,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.from_abi(abi),
        )

    @classmethod
    def from_FunctionDef(
        cls, node: vy_ast.FunctionDef, is_interface: Optional[bool] = False,
    ) -> "ContractFunction":
        """
        Generate a `ContractFunction` object from a `FunctionDef` node.

        Arguments
        ---------
        node : FunctionDef
            Vyper ast node to generate the function definition from.
        is_interface: bool, optional
            Boolean indicating if the function definition is part of an interface.

        Returns
        -------
        ContractFunction
        """
        kwargs: Dict[str, Any] = {}
        if is_interface:
            # FunctionDef with stateMutability in body (Interface defintions)
            if (
                len(node.body) == 1
                and isinstance(node.body[0], vy_ast.Expr)
                and isinstance(node.body[0].value, vy_ast.Name)
                and StateMutability.is_valid_value(node.body[0].value.id)
            ):
                # Interfaces are always public
                kwargs["function_visibility"] = FunctionVisibility.EXTERNAL
                kwargs["state_mutability"] = StateMutability(node.body[0].value.id)
            elif len(node.body) == 1 and node.body[0].get("value.id") in ("constant", "modifying"):
                if node.body[0].value.id == "constant":
                    expected = "view or pure"
                else:
                    expected = "payable or nonpayable"
                raise StructureException(
                    f"State mutability should be set to {expected}", node.body[0]
                )
            else:
                raise StructureException(
                    "Body must only contain state mutability label", node.body[0]
                )

        else:

            # FunctionDef with decorators (normal functions)
            for decorator in node.decorator_list:

                if isinstance(decorator, vy_ast.Call):
                    if "nonreentrant" in kwargs:
                        raise StructureException(
                            "nonreentrant decorator is already set with key: "
                            f"{kwargs['nonreentrant']}",
                            node,
                        )

                    if decorator.get("func.id") != "nonreentrant":
                        raise StructureException("Decorator is not callable", decorator)
                    if len(decorator.args) != 1 or not isinstance(decorator.args[0], vy_ast.Str):
                        raise StructureException(
                            "@nonreentrant name must be given as a single string literal",
                            decorator,
                        )

                    if node.name == "__init__":
                        msg = "Nonreentrant decorator disallowed on `__init__`"
                        raise FunctionDeclarationException(msg, decorator)

                    kwargs["nonreentrant"] = decorator.args[0].value

                elif isinstance(decorator, vy_ast.Name):
                    if FunctionVisibility.is_valid_value(decorator.id):
                        if "function_visibility" in kwargs:
                            raise FunctionDeclarationException(
                                f"Visibility is already set to: {kwargs['function_visibility']}",
                                node,
                            )
                        kwargs["function_visibility"] = FunctionVisibility(decorator.id)

                    elif StateMutability.is_valid_value(decorator.id):
                        if "state_mutability" in kwargs:
                            raise FunctionDeclarationException(
                                f"Mutability is already set to: {kwargs['state_mutability']}", node
                            )
                        kwargs["state_mutability"] = StateMutability(decorator.id)

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

        if "function_visibility" not in kwargs:
            raise FunctionDeclarationException(
                f"Visibility must be set to one of: {', '.join(FunctionVisibility.values())}", node
            )

        if node.name == "__default__":
            if kwargs["function_visibility"] != FunctionVisibility.EXTERNAL:
                raise FunctionDeclarationException(
                    "Default function must be marked as `@external`", node
                )
            if node.args.args:
                raise FunctionDeclarationException(
                    "Default function may not receive any arguments", node.args.args[0]
                )

        if "state_mutability" not in kwargs:
            # Assume nonpayable if not set at all (cannot accept Ether, but can modify state)
            kwargs["state_mutability"] = StateMutability.NONPAYABLE

        if (
            kwargs["state_mutability"] in (StateMutability.VIEW, StateMutability.PURE)
            and "nonreentrant" in kwargs
        ):
            raise StructureException("Cannot use reentrancy guard on view or pure functions", node)

        # call arguments
        if node.args.defaults and node.name == "__init__":
            raise FunctionDeclarationException(
                "Constructor may not use default arguments", node.args.defaults[0]
            )

        arguments = OrderedDict()
        max_arg_count = len(node.args.args)
        min_arg_count = max_arg_count - len(node.args.defaults)
        defaults = [None] * min_arg_count + node.args.defaults

        namespace = get_namespace()
        for arg, value in zip(node.args.args, defaults):
            if arg.arg in ("gas", "value"):
                raise ArgumentException(
                    f"Cannot use '{arg.arg}' as a variable name in a function input", arg,
                )
            if arg.arg in arguments:
                raise ArgumentException(f"Function contains multiple inputs named {arg.arg}", arg)
            if arg.arg in namespace:
                raise NamespaceCollision(arg.arg, arg)

            if arg.annotation is None:
                raise ArgumentException(f"Function argument '{arg.arg}' is missing a type", arg)

            type_definition = get_type_from_annotation(
                arg.annotation, location=DataLocation.CALLDATA, is_immutable=True
            )
            if isinstance(type_definition, StructDefinition) and type_definition.is_dynamic_size:
                # this is a temporary restriction and should be removed once support for dynamically
                # sized structs is implemented - https://github.com/vyperlang/vyper/issues/2190
                raise ArgumentException(
                    "Struct with dynamically sized data cannot be used as a function input", arg
                )

            if value is not None:
                if not check_constant(value):
                    raise StateAccessViolation(
                        "Value must be literal or environment variable", value
                    )
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

        return cls(node.name, arguments, min_arg_count, max_arg_count, return_type, **kwargs)

    def set_reentrancy_key_position(self, position: StorageSlot) -> None:
        if hasattr(self, "reentrancy_key_position"):
            raise CompilerPanic("Position was already assigned")
        if self.nonreentrant is None:
            raise CompilerPanic("No reentrant key {self}")
        # sanity check even though implied by the type
        if position._location != DataLocation.STORAGE:
            raise CompilerPanic("Non-storage reentrant key")
        self.reentrancy_key_position = position

    @classmethod
    def from_AnnAssign(cls, node: vy_ast.AnnAssign) -> "ContractFunction":
        """
        Generate a `ContractFunction` object from an `AnnAssign` node.

        Used to create function definitions for public variables.

        Arguments
        ---------
        node : AnnAssign
            Vyper ast node to generate the function definition from.

        Returns
        -------
        ContractFunction
        """
        if not isinstance(node.annotation, vy_ast.Call):
            raise CompilerPanic("Annotation must be a call to public()")
        type_ = get_type_from_annotation(node.annotation.args[0], location=DataLocation.STORAGE)
        arguments, return_type = type_.get_signature()
        args_dict: OrderedDict = OrderedDict()
        for item in arguments:
            args_dict[f"arg{len(args_dict)}"] = item
        return cls(
            node.target.id,
            args_dict,
            len(arguments),
            len(arguments),
            return_type,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.VIEW,
        )

    @property
    def method_ids(self) -> Dict[str, int]:
        """
        Dict of `{signature: four byte selector}` for this function.

        * For functions without default arguments the dict contains one item.
        * For functions with default arguments, there is one key for each
          function signfature.
        """
        arg_types = [i.canonical_type for i in self.arguments.values()]

        if not self.has_default_args:
            return _generate_method_id(self.name, arg_types)

        method_ids = {}
        for i in range(self.min_arg_count, self.max_arg_count + 1):
            method_ids.update(_generate_method_id(self.name, arg_types[:i]))
        return method_ids

    @property
    def is_constructor(self) -> bool:
        return self.name == "__init__"

    @property
    def is_fallback(self) -> bool:
        return self.name == "__default__"

    @property
    def has_default_args(self) -> bool:
        return self.min_arg_count < self.max_arg_count

    def get_signature(self) -> Tuple[Tuple, Optional[BaseTypeDefinition]]:
        return tuple(self.arguments.values()), self.return_type

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[BaseTypeDefinition]:
        if node.get("func.value.id") == "self" and self.visibility == FunctionVisibility.EXTERNAL:
            raise CallViolation("Cannnot call external functions via 'self'", node)

        # for external calls, include gas and value as optional kwargs
        kwarg_keys = self.kwarg_keys.copy()
        if node.get("func.value.id") != "self":
            kwarg_keys += ["gas", "value"]
        validate_call_args(node, (self.min_arg_count, self.max_arg_count), kwarg_keys)

        if self.mutability < StateMutability.PAYABLE:
            kwarg_node = next((k for k in node.keywords if k.arg == "value"), None)
            if kwarg_node is not None:
                raise CallViolation("Cannnot send ether to nonpayable function", kwarg_node)

        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)

        for kwarg in node.keywords:
            if kwarg.arg in ("gas", "value"):
                validate_expected_type(kwarg.value, Uint256Definition())
            else:
                validate_expected_type(kwarg.arg, kwarg.value)

        return self.return_type

    def to_abi_dict(self) -> List[Dict]:
        abi_dict: Dict = {"stateMutability": self.mutability.value}

        if self.is_fallback:
            abi_dict["type"] = "fallback"
            return [abi_dict]

        if self.is_constructor:
            abi_dict["type"] = "constructor"
        else:
            abi_dict["type"] = "function"
            abi_dict["name"] = self.name

        abi_dict["inputs"] = [_generate_abi_type(v, k) for k, v in self.arguments.items()]

        typ = self.return_type
        if typ is None:
            abi_dict["outputs"] = []
        elif isinstance(typ, TupleDefinition):
            abi_dict["outputs"] = [_generate_abi_type(i) for i in typ.value_type]  # type: ignore
        elif isinstance(typ, StructDefinition):
            abi_dict["outputs"] = [_generate_abi_type(v, k) for k, v in typ.members.items()]
        else:
            abi_dict["outputs"] = [_generate_abi_type(typ)]

        if self.has_default_args:
            # for functions with default args, return a dict for each possible arg count
            result = []
            for i in range(self.min_arg_count, self.max_arg_count + 1):
                result.append(abi_dict.copy())
                result[-1]["inputs"] = result[-1]["inputs"][:i]
            return result
        else:
            return [abi_dict]


def _generate_abi_type(type_definition, name=""):
    if isinstance(type_definition, StructDefinition):
        return {
            "name": name,
            "type": "tuple",
            "components": [_generate_abi_type(v, k) for k, v in type_definition.members.items()],
        }
    return {"name": name, "type": type_definition.canonical_type}


def _generate_method_id(name: str, canonical_types: List[str]) -> Dict[str, int]:
    function_sig = f"{name}({','.join(canonical_types)})"
    selector = keccak256(function_sig.encode())[:4].hex()
    return {function_sig: int(selector, 16)}
