import re
import warnings
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    CompilerPanic,
    FunctionDeclarationException,
    InvalidType,
    StateAccessViolation,
    StructureException,
)
from vyper.semantics.analysis.base import FunctionVisibility, StateMutability, StorageSlot
from vyper.semantics.analysis.utils import check_kwargable, validate_expected_type
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import KwargSettings, VyperType
from vyper.semantics.types.primitives import BoolT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import TupleT
from vyper.semantics.types.utils import type_from_abi, type_from_annotation
from vyper.utils import OrderedSet, keccak256


@dataclass
class _FunctionArg:
    name: str
    typ: VyperType


@dataclass
class PositionalArg(_FunctionArg):
    ast_source: Optional[vy_ast.VyperNode] = None


@dataclass
class KeywordArg(_FunctionArg):
    default_value: vy_ast.VyperNode
    ast_source: Optional[vy_ast.VyperNode] = None


class ContractFunctionT(VyperType):
    """
    Contract function type.

    Functions compare false against all types and so cannot be assigned without
    being called. Calls are validated by `fetch_call_return`, check the call
    arguments against `positional_args` and `keyword_arg`, and return `return_type`.

    Attributes
    ----------
    name : str
        The name of the function.
    positional_args: list[PositionalArg]
        Positional args for this function
    keyword_args: list[KeywordArg]
        Keyword args for this function
    return_type: Optional[VyperType]
        Type of return value
    function_visibility : FunctionVisibility
        enum indicating the external visibility of a function.
    state_mutability : StateMutability
        enum indicating the authority a function has to mutate it's own state.
    nonreentrant : Optional[str]
        Re-entrancy lock name.
    """

    _is_callable = True

    def __init__(
        self,
        name: str,
        positional_args: list[PositionalArg],
        keyword_args: list[KeywordArg],
        return_type: Optional[VyperType],
        function_visibility: FunctionVisibility,
        state_mutability: StateMutability,
        nonreentrant: Optional[str] = None,
    ) -> None:
        super().__init__()

        self.name = name
        self.positional_args = positional_args
        self.keyword_args = keyword_args
        self.return_type = return_type
        self.visibility = function_visibility
        self.mutability = state_mutability
        self.nonreentrant = nonreentrant

        # a list of internal functions this function calls
        self.called_functions = OrderedSet()

        # to be populated during codegen
        self._ir_info: Any = None

    @cached_property
    def call_site_kwargs(self):
        # special kwargs that are allowed in call site
        return {
            "gas": KwargSettings(UINT256_T, "gas"),
            "value": KwargSettings(UINT256_T, 0),
            "skip_contract_check": KwargSettings(BoolT(), False, require_literal=True),
            "default_return_value": KwargSettings(self.return_type, None),
        }

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self.argument_types)
        return f"contract function {self.name}({arg_types})"

    def __str__(self):
        ret_sig = "" if not self.return_type else f" -> {self.return_type}"
        args_sig = ",".join([str(t) for t in self.argument_types])
        return f"def {self.name} {args_sig}{ret_sig}:"

    # override parent implementation. function type equality does not
    # make too much sense.
    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return hash(id(self))

    @classmethod
    def from_abi(cls, abi: Dict) -> "ContractFunctionT":
        """
        Generate a `ContractFunctionT` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing a function.

        Returns
        -------
        ContractFunctionT object.
        """
        positional_args = []
        for item in abi["inputs"]:
            positional_args.append(PositionalArg(item["name"], type_from_abi(item)))
        return_type = None
        if len(abi["outputs"]) == 1:
            return_type = type_from_abi(abi["outputs"][0])
        elif len(abi["outputs"]) > 1:
            return_type = TupleT(tuple(type_from_abi(i) for i in abi["outputs"]))
        return cls(
            abi["name"],
            positional_args,
            [],
            return_type,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.from_abi(abi),
        )

    @classmethod
    def from_FunctionDef(
        cls, node: vy_ast.FunctionDef, is_interface: Optional[bool] = False
    ) -> "ContractFunctionT":
        """
        Generate a `ContractFunctionT` object from a `FunctionDef` node.

        Arguments
        ---------
        node : FunctionDef
            Vyper ast node to generate the function definition from.
        is_interface: bool, optional
            Boolean indicating if the function definition is part of an interface.

        Returns
        -------
        ContractFunctionT
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
                            "@nonreentrant name must be given as a single string literal", decorator
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

        if kwargs["state_mutability"] == StateMutability.PURE and "nonreentrant" in kwargs:
            raise StructureException("Cannot use reentrancy guard on pure functions", node)

        if node.name == "__init__":
            if (
                kwargs["state_mutability"] in (StateMutability.PURE, StateMutability.VIEW)
                or kwargs["function_visibility"] == FunctionVisibility.INTERNAL
            ):
                raise FunctionDeclarationException(
                    "Constructor cannot be marked as `@pure`, `@view` or `@internal`", node
                )

            # call arguments
            if node.args.defaults:
                raise FunctionDeclarationException(
                    "Constructor may not use default arguments", node.args.defaults[0]
                )

        argnames = set()  # for checking uniqueness
        n_total_args = len(node.args.args)
        n_positional_args = n_total_args - len(node.args.defaults)

        positional_args: list[PositionalArg] = []
        keyword_args: list[KeywordArg] = []

        for i, arg in enumerate(node.args.args):
            argname = arg.arg
            if argname in ("gas", "value", "skip_contract_check", "default_return_value"):
                raise ArgumentException(
                    f"Cannot use '{argname}' as a variable name in a function input", arg
                )
            if argname in argnames:
                raise ArgumentException(f"Function contains multiple inputs named {argname}", arg)

            if arg.annotation is None:
                raise ArgumentException(f"Function argument '{argname}' is missing a type", arg)

            type_ = type_from_annotation(arg.annotation, DataLocation.CALLDATA)

            if i < n_positional_args:
                positional_args.append(PositionalArg(argname, type_, ast_source=arg))
            else:
                value = node.args.defaults[i - n_positional_args]
                if not check_kwargable(value):
                    raise StateAccessViolation(
                        "Value must be literal or environment variable", value
                    )
                validate_expected_type(value, type_)
                keyword_args.append(KeywordArg(argname, type_, value, ast_source=arg))

            argnames.add(argname)

        # return types
        if node.returns is None:
            return_type = None
        elif node.name == "__init__":
            raise FunctionDeclarationException(
                "Constructor may not have a return type", node.returns
            )
        elif isinstance(node.returns, (vy_ast.Name, vy_ast.Subscript, vy_ast.Tuple)):
            # note: consider, for cleanliness, adding DataLocation.RETURN_VALUE
            return_type = type_from_annotation(node.returns, DataLocation.MEMORY)
        else:
            raise InvalidType("Function return value must be a type name or tuple", node.returns)

        return cls(node.name, positional_args, keyword_args, return_type, **kwargs)

    def set_reentrancy_key_position(self, position: StorageSlot) -> None:
        if hasattr(self, "reentrancy_key_position"):
            raise CompilerPanic("Position was already assigned")
        if self.nonreentrant is None:
            raise CompilerPanic(f"No reentrant key {self}")
        # sanity check even though implied by the type
        if position._location != DataLocation.STORAGE:
            raise CompilerPanic("Non-storage reentrant key")
        self.reentrancy_key_position = position

    @classmethod
    def getter_from_VariableDecl(cls, node: vy_ast.VariableDecl) -> "ContractFunctionT":
        """
        Generate a `ContractFunctionT` object from an `VariableDecl` node.

        Used to create getter functions for public variables.

        Arguments
        ---------
        node : VariableDecl
            Vyper ast node to generate the function definition from.

        Returns
        -------
        ContractFunctionT
        """
        if not node.is_public:
            raise CompilerPanic("getter generated for non-public function")
        type_ = type_from_annotation(node.annotation, DataLocation.STORAGE)
        arguments, return_type = type_.getter_signature
        args = []
        for i, item in enumerate(arguments):
            args.append(PositionalArg(f"arg{i}", item))

        return cls(
            node.target.id,
            args,
            [],
            return_type,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.VIEW,
        )

    @property
    # convenience property for compare_signature, as it would
    # appear in a public interface
    def _iface_sig(self) -> Tuple[Tuple, Optional[VyperType]]:
        return tuple(self.argument_types), self.return_type

    def implements(self, other: "ContractFunctionT") -> bool:
        """
        Checks if this function implements the signature of another
        function.

        Used when determining if an interface has been implemented. This method
        should not be directly implemented by any inherited classes.
        """

        if not self.is_external:
            return False

        arguments, return_type = self._iface_sig
        other_arguments, other_return_type = other._iface_sig

        if len(arguments) != len(other_arguments):
            return False
        for atyp, btyp in zip(arguments, other_arguments):
            if not atyp.compare_type(btyp):
                return False

        if return_type and not return_type.compare_type(other_return_type):  # type: ignore
            return False

        if self.mutability > other.mutability:
            return False

        return True

    @cached_property
    def default_values(self) -> dict[str, vy_ast.VyperNode]:
        return {arg.name: arg.default_value for arg in self.keyword_args}

    # for backwards compatibility
    @cached_property
    def arguments(self) -> list[_FunctionArg]:
        return self.positional_args + self.keyword_args  # type: ignore

    @cached_property
    def argument_types(self) -> list[VyperType]:
        return [arg.typ for arg in self.arguments]

    @property
    def n_positional_args(self) -> int:
        return len(self.positional_args)

    @property
    def n_keyword_args(self) -> int:
        return len(self.keyword_args)

    @cached_property
    def n_total_args(self) -> int:
        return self.n_positional_args + self.n_keyword_args

    @property
    def is_external(self) -> bool:
        return self.visibility == FunctionVisibility.EXTERNAL

    @property
    def is_internal(self) -> bool:
        return self.visibility == FunctionVisibility.INTERNAL

    @property
    def is_mutable(self) -> bool:
        return self.mutability > StateMutability.VIEW

    @property
    def is_payable(self) -> bool:
        return self.mutability == StateMutability.PAYABLE

    @property
    def is_constructor(self) -> bool:
        return self.name == "__init__"

    @property
    def is_fallback(self) -> bool:
        return self.name == "__default__"

    @property
    def method_ids(self) -> Dict[str, int]:
        """
        Dict of `{signature: four byte selector}` for this function.

        * For functions without default arguments the dict contains one item.
        * For functions with default arguments, there is one key for each
          function signature.
        """
        arg_types = [i.canonical_abi_type for i in self.argument_types]

        if self.n_keyword_args == 0:
            return _generate_method_id(self.name, arg_types)

        method_ids = {}
        for i in range(self.n_positional_args, self.n_total_args + 1):
            method_ids.update(_generate_method_id(self.name, arg_types[:i]))
        return method_ids

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[VyperType]:
        if node.get("func.value.id") == "self" and self.visibility == FunctionVisibility.EXTERNAL:
            raise CallViolation("Cannot call external functions via 'self'", node)

        # for external calls, include gas and value as optional kwargs
        kwarg_keys = [arg.name for arg in self.keyword_args]
        if not self.is_internal:
            kwarg_keys += list(self.call_site_kwargs.keys())
        validate_call_args(node, (self.n_positional_args, self.n_total_args), kwarg_keys)

        if self.mutability < StateMutability.PAYABLE:
            kwarg_node = next((k for k in node.keywords if k.arg == "value"), None)
            if kwarg_node is not None:
                raise CallViolation("Cannot send ether to nonpayable function", kwarg_node)

        for arg, expected in zip(node.args, self.argument_types):
            validate_expected_type(arg, expected)

        # TODO this should be moved to validate_call_args
        for kwarg in node.keywords:
            if kwarg.arg in self.call_site_kwargs:
                kwarg_settings = self.call_site_kwargs[kwarg.arg]
                if kwarg.arg == "default_return_value" and self.return_type is None:
                    raise ArgumentException(
                        f"`{kwarg.arg}=` specified but {self.name}() does not return anything",
                        kwarg.value,
                    )
                validate_expected_type(kwarg.value, kwarg_settings.typ)
                if kwarg_settings.require_literal:
                    if not isinstance(kwarg.value, vy_ast.Constant):
                        raise InvalidType(
                            f"{kwarg.arg} must be literal {kwarg_settings.typ}", kwarg.value
                        )
            else:
                # Generate the modified source code string with the kwarg removed
                # as a suggestion to the user.
                kwarg_pattern = rf"{kwarg.arg}\s*=\s*{re.escape(kwarg.value.node_source_code)}"
                modified_line = re.sub(
                    kwarg_pattern, kwarg.value.node_source_code, node.node_source_code
                )
                error_suggestion = (
                    f"\n(hint: Try removing the kwarg: `{modified_line}`)"
                    if modified_line != node.node_source_code
                    else ""
                )

                raise ArgumentException(
                    (
                        "Usage of kwarg in Vyper is restricted to "
                        + ", ".join([f"{k}=" for k in self.call_site_kwargs.keys()])
                        + f". {error_suggestion}"
                    ),
                    kwarg,
                )

        return self.return_type

    def to_toplevel_abi_dict(self):
        abi_dict: Dict = {"stateMutability": self.mutability.value}

        if self.is_fallback:
            abi_dict["type"] = "fallback"
            return [abi_dict]

        if self.is_constructor:
            abi_dict["type"] = "constructor"
        else:
            abi_dict["type"] = "function"
            abi_dict["name"] = self.name

        abi_dict["inputs"] = [arg.typ.to_abi_arg(name=arg.name) for arg in self.arguments]

        typ = self.return_type
        if typ is None:
            abi_dict["outputs"] = []
        elif isinstance(typ, TupleT) and len(typ.member_types) > 1:
            abi_dict["outputs"] = [t.to_abi_arg() for t in typ.member_types]
        else:
            abi_dict["outputs"] = [typ.to_abi_arg()]

        if self.n_keyword_args > 0:
            # for functions with default args, return a dict for each possible arg count
            result = []
            for i in range(self.n_positional_args, self.n_total_args + 1):
                result.append(abi_dict.copy())
                result[-1]["inputs"] = result[-1]["inputs"][:i]
            return result
        else:
            return [abi_dict]

    # calculate the abi signature for a given set of kwargs
    def abi_signature_for_kwargs(self, kwargs: list[KeywordArg]) -> str:
        args = self.positional_args + kwargs  # type: ignore
        return self.name + "(" + ",".join([arg.typ.abi_type.selector_name() for arg in args]) + ")"


class MemberFunctionT(VyperType):
    """
    Member function type definition.

    This class has no corresponding primitive.

    (examples for (x <DynArray[int128, 3]>).append(1))

    Arguments:
        underlying_type: the type this method is attached to. ex. DynArray[int128, 3]
        name: the name of this method. ex. "append"
        arg_types: the argument types this method accepts. ex. [int128]
        return_type: the return type of this method. ex. None
    """

    _is_callable = True

    # keep LGTM linter happy
    def __eq__(self, other):
        return super().__eq__(other)

    def __init__(
        self,
        underlying_type: VyperType,
        name: str,
        arg_types: List[VyperType],
        return_type: Optional[VyperType],
        is_modifying: bool,
    ) -> None:
        super().__init__()

        self.underlying_type = underlying_type
        self.name = name
        self.arg_types = arg_types
        self.return_type = return_type
        self.is_modifying = is_modifying

    def __repr__(self):
        return f"{self.underlying_type._id} member function '{self.name}'"

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[VyperType]:
        validate_call_args(node, len(self.arg_types))

        assert len(node.args) == len(self.arg_types)  # validate_call_args postcondition
        for arg, expected_type in zip(node.args, self.arg_types):
            # CMC 2022-04-01 this should probably be in the validation module
            validate_expected_type(arg, expected_type)

        return self.return_type


def _generate_method_id(name: str, canonical_abi_types: List[str]) -> Dict[str, int]:
    function_sig = f"{name}({','.join(canonical_abi_types)})"
    selector = keccak256(function_sig.encode())[:4].hex()
    return {function_sig: int(selector, 16)}
