import re
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.compiler.settings import Settings
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    CompilerPanic,
    FunctionDeclarationException,
    InvalidType,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
)
from vyper.semantics.analysis.base import (
    FunctionVisibility,
    Modifiability,
    ModuleInfo,
    StateMutability,
    VarAccess,
    VarOffset,
)
from vyper.semantics.analysis.utils import (
    check_modifiability,
    get_exact_type_from_node,
    uses_state,
    validate_expected_type,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import KwargSettings, VyperType
from vyper.semantics.types.bytestrings import BytesT
from vyper.semantics.types.primitives import BoolT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import TupleT
from vyper.semantics.types.utils import type_from_abi, type_from_annotation
from vyper.utils import OrderedSet, keccak256


@dataclass
class _FunctionArg:
    name: str
    typ: VyperType
    ast_source: Optional[vy_ast.VyperNode] = None


@dataclass
class PositionalArg(_FunctionArg):
    pass


@dataclass(kw_only=True)
class KeywordArg(_FunctionArg):
    default_value: vy_ast.VyperNode


# TODO: refactor this into FunctionT (from an ast) and ABIFunctionT (from json)
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
    nonreentrant : bool
        Whether this function is marked `@nonreentrant` or not
    """

    typeclass = "contract_function"

    _is_callable = True

    def __init__(
        self,
        name: str,
        positional_args: list[PositionalArg],
        keyword_args: list[KeywordArg],
        return_type: Optional[VyperType],
        function_visibility: FunctionVisibility,
        state_mutability: StateMutability,
        from_interface: bool = False,
        nonreentrant: bool = False,
        do_raw_return: bool = False,
        ast_def: Optional[vy_ast.VyperNode] = None,
    ) -> None:
        super().__init__()

        self.name = name
        self.positional_args = positional_args
        self.keyword_args = keyword_args
        self.return_type = return_type
        self.visibility = function_visibility
        self.mutability = state_mutability
        self.nonreentrant = nonreentrant
        self.do_raw_return = do_raw_return
        self.from_interface = from_interface

        # sanity check, nonreentrant used to be Optional[str]
        assert isinstance(self.nonreentrant, bool)

        self.ast_def = ast_def

        self._analysed = False

        # a list of internal functions this function calls.
        # to be populated during module analysis.
        self.called_functions: OrderedSet[ContractFunctionT] = OrderedSet()

        # recursively reachable from this function
        # to be populated during module analysis.
        self.reachable_internal_functions: OrderedSet[ContractFunctionT] = OrderedSet()

        # writes to variables from this function
        self._variable_writes: OrderedSet[VarAccess] = OrderedSet()

        # reads of variables from this function
        self._variable_reads: OrderedSet[VarAccess] = OrderedSet()

        # list of modules used (accessed state) by this function
        self._used_modules: OrderedSet[ModuleInfo] = OrderedSet()

        # to be populated during codegen
        self._ir_info: Any = None
        self._function_id: Optional[int] = None

    @property
    # API compatibility
    def decl_node(self):
        return self.ast_def

    @property
    def _id(self):
        return self.name

    def mark_analysed(self):
        assert not self._analysed
        self._analysed = True

    @property
    def analysed(self):
        return self._analysed

    def get_variable_reads(self):
        return self._variable_reads

    def get_variable_writes(self):
        return self._variable_writes

    def get_variable_accesses(self):
        return self._variable_reads | self._variable_writes

    def uses_state(self):
        return (
            self.nonreentrant
            or uses_state(self.get_variable_accesses())
            or any(f.nonreentrant for f in self.reachable_internal_functions)
        )

    def get_used_modules(self):
        # _used_modules is populated during analysis
        return self._used_modules

    def mark_used_module(self, module_info):
        self._used_modules.add(module_info)

    def mark_variable_writes(self, var_infos):
        self._variable_writes.update(var_infos)

    def mark_variable_reads(self, var_infos):
        self._variable_reads.update(var_infos)

    @property
    def modifiability(self):
        return Modifiability.from_state_mutability(self.mutability)

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
        return f"def {self.name}({args_sig}){ret_sig}:"

    @cached_property
    def _pp_signature(self):
        ret = ",".join(repr(arg.typ) for arg in self.arguments)
        return f"{self.name}({ret})"

    # override parent implementation. function type equality does not
    # make too much sense.
    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return hash(id(self))

    @classmethod
    def from_abi(cls, abi: dict) -> "ContractFunctionT":
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
            from_interface=True,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.from_abi(abi),
        )

    @classmethod
    def from_InterfaceDef(cls, funcdef: vy_ast.FunctionDef) -> "ContractFunctionT":
        """
        Generate a `ContractFunctionT` object from a `FunctionDef` inside
        of an `InterfaceDef`

        Arguments
        ---------
        funcdef: FunctionDef
            Vyper ast node to generate the function definition from.

        Returns
        -------
        ContractFunctionT
        """
        # FunctionDef with stateMutability in body (Interface definitions)
        body = funcdef.body
        if (
            len(body) == 1
            and isinstance(body[0], vy_ast.Expr)
            and isinstance(body[0].value, vy_ast.Name)
            and StateMutability.is_valid_value(body[0].value.id)
        ):
            # Interfaces are always public
            function_visibility = FunctionVisibility.EXTERNAL
            state_mutability = StateMutability(body[0].value.id)
        # handle errors
        elif len(body) == 1 and body[0].get("value.id") in ("constant", "modifying"):
            if body[0].value.id == "constant":
                expected = "view or pure"
            else:
                expected = "payable or nonpayable"
            raise StructureException(f"State mutability should be set to {expected}", body[0])
        else:
            raise StructureException("Body must only contain state mutability label", body[0])

        if funcdef.name == "__init__":
            raise FunctionDeclarationException("Constructors cannot appear in interfaces", funcdef)

        if funcdef.name == "__default__":
            raise FunctionDeclarationException(
                "Default functions cannot appear in interfaces", funcdef
            )

        positional_args, keyword_args = _parse_args(funcdef)

        return_type = _parse_return_type(funcdef)

        return cls(
            funcdef.name,
            positional_args,
            keyword_args,
            return_type,
            function_visibility,
            state_mutability,
            from_interface=True,
            nonreentrant=False,
            ast_def=funcdef,
        )

    @classmethod
    def from_vyi(cls, funcdef: vy_ast.FunctionDef) -> "ContractFunctionT":
        """
        Generate a `ContractFunctionT` object from a `FunctionDef` inside
        of an interface (`.vyi`) file

        Arguments
        ---------
        funcdef: FunctionDef
            Vyper ast node to generate the function definition from.

        Returns
        -------
        ContractFunctionT
        """
        decorators = _parse_decorators(funcdef)

        if decorators.nonreentrant_node is not None:
            raise FunctionDeclarationException(
                "`@nonreentrant` not allowed in interfaces", decorators.nonreentrant_node
            )

        # guaranteed by parse_decorators and disallowing nonreentrant pragma
        assert decorators.reentrant_node is None  # sanity check

        if decorators.raw_return_node is not None:
            raise FunctionDeclarationException(
                "`@raw_return` not allowed in interfaces", decorators.raw_return_node
            )

        # it's redundant to specify visibility in vyi - always should be external
        function_visibility = decorators.visibility
        if function_visibility is None:
            function_visibility = FunctionVisibility.EXTERNAL

        if function_visibility != FunctionVisibility.EXTERNAL:
            raise FunctionDeclarationException(
                "Interface functions can only be marked as `@external`", decorators.visibility_node
            )

        if funcdef.name == "__init__":
            raise FunctionDeclarationException("Constructors cannot appear in interfaces", funcdef)

        if funcdef.name == "__default__":
            raise FunctionDeclarationException(
                "Default functions cannot appear in interfaces", funcdef
            )

        positional_args, keyword_args = _parse_args(funcdef)

        return_type = _parse_return_type(funcdef)

        body = funcdef.body

        if len(body) != 1 or not (
            isinstance(body[0], vy_ast.Expr) and isinstance(body[0].value, vy_ast.Ellipsis)
        ):
            raise FunctionDeclarationException(
                "function body in an interface can only be `...`!", funcdef
            )

        return cls(
            funcdef.name,
            positional_args,
            keyword_args,
            return_type,
            function_visibility,
            decorators.state_mutability,
            from_interface=True,
            nonreentrant=False,
            ast_def=funcdef,
        )

    @classmethod
    def from_FunctionDef(cls, funcdef: vy_ast.FunctionDef) -> "ContractFunctionT":
        """
        Generate a `ContractFunctionT` object from a `FunctionDef` node.

        Arguments
        ---------
        funcdef: FunctionDef
            Vyper ast node to generate the function definition from.

        Returns
        -------
        ContractFunctionT
        """
        decorators = _parse_decorators(funcdef)

        # it's redundant to specify internal visibility - it's implied by not being external
        function_visibility = decorators.visibility
        if function_visibility is None:
            function_visibility = FunctionVisibility.INTERNAL

        positional_args, keyword_args = _parse_args(funcdef)

        return_type = _parse_return_type(funcdef)

        # validate default and init functions
        if funcdef.name == "__default__":
            if function_visibility != FunctionVisibility.EXTERNAL:
                raise FunctionDeclarationException(
                    "Default function must be marked as `@external`", funcdef
                )
            if funcdef.args.args:
                raise FunctionDeclarationException(
                    "Default function may not receive any arguments", funcdef.args.args[0]
                )

        if function_visibility == FunctionVisibility.DEPLOY and funcdef.name != "__init__":
            raise FunctionDeclarationException(
                "Only constructors can be marked as `@deploy`!", funcdef
            )
        if funcdef.name == "__init__":
            if decorators.state_mutability in (StateMutability.PURE, StateMutability.VIEW):
                raise FunctionDeclarationException(
                    "Constructor cannot be marked as `@pure` or `@view`", funcdef
                )
            if function_visibility != FunctionVisibility.DEPLOY:
                raise FunctionDeclarationException(
                    "Constructor must be marked as `@deploy`", funcdef
                )
            if return_type is not None:
                raise FunctionDeclarationException(
                    "Constructor may not have a return type", funcdef.returns
                )

            # call arguments
            if funcdef.args.defaults:
                raise FunctionDeclarationException(
                    "Constructor may not use default arguments", funcdef.args.defaults[0]
                )
            if decorators.nonreentrant_node is not None:
                msg = "`@nonreentrant` decorator disallowed on `__init__`"
                raise FunctionDeclarationException(msg, decorators.nonreentrant_node)

        if decorators.raw_return:
            if function_visibility != FunctionVisibility.EXTERNAL:
                raise StructureException(
                    "@raw_return is only allowed on external functions!", decorators.raw_return_node
                )
            if not isinstance(return_type, BytesT):
                raise StructureException(
                    "@raw_return is only allowed in conjunction with `Bytes[...]` return type!",
                    decorators.raw_return_node,
                )

        # compute nonreentrancy
        settings = funcdef.module_node.settings
        nonreentrant: bool
        is_external = function_visibility == FunctionVisibility.EXTERNAL
        is_pure = decorators.state_mutability == StateMutability.PURE

        if is_pure:
            # pure functions are always nonreentrant
            nonreentrant = False
        elif settings.nonreentrancy_by_default:
            if not is_external:
                # default, internal functions default to reentrant even if
                # the pragma is set
                nonreentrant = decorators.nonreentrant_node is not None
            else:
                # validation -- cannot use `@nonreentrant` on external
                # functions if nonreentrant pragma is set
                if decorators.nonreentrant_node is not None:
                    raise StructureException(
                        "used @nonreentrant decorator, but `#pragma nonreentrancy` is set"
                    )
                nonreentrant = decorators.reentrant_node is None
        else:
            nonreentrant = decorators.nonreentrant_node is not None

        return cls(
            funcdef.name,
            positional_args,
            keyword_args,
            return_type,
            function_visibility,
            decorators.state_mutability,
            from_interface=False,
            nonreentrant=nonreentrant,
            do_raw_return=decorators.raw_return,
            ast_def=funcdef,
        )

    def set_reentrancy_key_position(self, position: VarOffset) -> None:
        if hasattr(self, "reentrancy_key_position"):
            raise CompilerPanic("Position was already assigned")
        if not self.nonreentrant:
            raise CompilerPanic(f"Not nonreentrant {self}", self.ast_def)

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

        # calculated by caller (ModuleAnalyzer.visit_VariableDecl)
        type_ = node.target._metadata["varinfo"].typ

        arguments, return_type = type_.getter_signature
        args = []
        for i, item in enumerate(arguments):
            args.append(PositionalArg(f"arg{i}", item))

        return cls(
            node.target.id,
            args,
            [],
            return_type,
            from_interface=False,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.VIEW,
            ast_def=node,
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
        if not self.is_external:  # pragma: nocover
            raise CompilerPanic("unreachable!")

        assert self.visibility == other.visibility

        arguments, return_type = self._iface_sig
        other_arguments, other_return_type = other._iface_sig

        if len(arguments) != len(other_arguments):
            return False
        for atyp, btyp in zip(arguments, other_arguments):
            if not atyp.compare_type(btyp):
                return False

        if return_type and not return_type.compare_type(other_return_type):  # type: ignore
            return False

        return self.mutability == other.mutability

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
    def is_deploy(self) -> bool:
        return self.visibility == FunctionVisibility.DEPLOY

    @property
    def is_constructor(self) -> bool:
        return self.name == "__init__"

    @property
    def is_mutable(self) -> bool:
        return self.mutability > StateMutability.VIEW

    @property
    def is_payable(self) -> bool:
        return self.mutability == StateMutability.PAYABLE

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

    # add more information to type exceptions generated inside calls
    def _enhance_call_exception(self, e, ast_node=None):
        if ast_node is not None:
            e.append_annotation(ast_node)
        elif e.hint is None:
            # try really hard to give the user a signature
            e.hint = self._pp_signature
        return e

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[VyperType]:
        # mypy hint - right now, the only way a ContractFunctionT can be
        # called is via `Attribute`, e.x. self.foo() or library.bar()
        assert isinstance(node.func, vy_ast.Attribute)
        parent_t = get_exact_type_from_node(node.func.value)
        if not parent_t._supports_external_calls and self.visibility == FunctionVisibility.EXTERNAL:
            raise CallViolation("Cannot call external functions via 'self' or via library", node)

        kwarg_keys = []
        # for external calls, include gas and value as optional kwargs
        if not self.is_internal:
            kwarg_keys += list(self.call_site_kwargs.keys())
        try:
            validate_call_args(node, (self.n_positional_args, self.n_total_args), kwarg_keys)
        except ArgumentException as e:
            raise self._enhance_call_exception(e, self.ast_def)

        if self.mutability < StateMutability.PAYABLE:
            kwarg_node = next((k for k in node.keywords if k.arg == "value"), None)
            if kwarg_node is not None:
                raise CallViolation("Cannot send ether to nonpayable function", kwarg_node)

        for arg, expected in zip(node.args, self.arguments):
            try:
                validate_expected_type(arg, expected.typ)
            except TypeMismatch as e:
                raise self._enhance_call_exception(e, expected.ast_source or self.ast_def)

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

                msg = "Usage of kwarg in Vyper is restricted to "
                msg += ", ".join([f"{k}=" for k in self.call_site_kwargs.keys()])

                hint = None
                if modified_line != node.node_source_code:
                    hint = f"Try removing the kwarg: `{modified_line}`"
                raise ArgumentException(msg, kwarg, hint=hint)

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


def _parse_return_type(funcdef: vy_ast.FunctionDef) -> Optional[VyperType]:
    # return types
    if funcdef.returns is None:
        return None
    # note: consider, for cleanliness, adding DataLocation.RETURN_VALUE
    return type_from_annotation(funcdef.returns, DataLocation.MEMORY)


@dataclass
class _ParsedDecorators:
    visibility_node: Optional[vy_ast.Name] = None
    state_mutability_node: Optional[vy_ast.Name] = None
    nonreentrant_node: Optional[vy_ast.Name] = None
    raw_return_node: Optional[vy_ast.Name] = None
    reentrant_node: Optional[vy_ast.Name] = None

    def __init__(self, funcdef: vy_ast.FunctionDef):
        self.funcdef = funcdef

    def set_visibility(self, decorator_node: vy_ast.Name):
        assert FunctionVisibility.is_valid_value(decorator_node.id), "unreachable"
        if self.visibility_node is not None:
            raise FunctionDeclarationException(
                f"Visibility is already set to: {self.visibility}",
                self.visibility_node,
                decorator_node,
                hint="only one visibility decorator is allowed per function",
            )
        self.visibility_node = decorator_node

    @property
    def visibility(self) -> Optional[FunctionVisibility]:
        if self.visibility_node is None:
            return None
        return FunctionVisibility(self.visibility_node.id)

    def set_state_mutability(self, decorator_node: vy_ast.Name):
        assert StateMutability.is_valid_value(decorator_node.id), "unreachable"
        self._check_none(self.state_mutability_node, decorator_node)
        self.state_mutability_node = decorator_node

    @property
    def state_mutability(self) -> StateMutability:
        if self.state_mutability_node is None:
            return StateMutability.NONPAYABLE  # default
        return StateMutability(self.state_mutability_node.id)

    def get_file_settings(self) -> Settings:
        return self.funcdef.module_node.settings

    def _check_none(self, node_a, node_b):
        if node_a is not None:
            name_a = node_a.id
            name_b = node_b.id
            raise FunctionDeclarationException(
                f"tried to set {name_b}, but {name_a} is already set", node_a, node_b
            )

    def set_nonreentrant(self, decorator_node: vy_ast.Name):
        self._check_none(self.nonreentrant_node, decorator_node)
        self._check_none(self.reentrant_node, decorator_node)

        self.nonreentrant_node = decorator_node

    def set_reentrant(self, decorator_node: vy_ast.Name):
        self._check_none(self.nonreentrant_node, decorator_node)
        self._check_none(self.reentrant_node, decorator_node)

        settings = self.get_file_settings()

        if not settings.nonreentrancy_by_default:
            raise StructureException(
                "used @reentrant decorator, but `#pragma nonreentrancy` is not set"
            )

        self.reentrant_node = decorator_node

    def set_raw_return(self, decorator_node: vy_ast.Name):
        if self.raw_return_node is not None:
            raise StructureException(
                "raw_return decorator is already set", self.raw_return_node, decorator_node
            )

        self.raw_return_node = decorator_node

    @property
    def raw_return(self) -> bool:
        return self.raw_return_node is not None


def _parse_decorators(funcdef: vy_ast.FunctionDef) -> _ParsedDecorators:
    ret = _ParsedDecorators(funcdef)

    for decorator in funcdef.decorator_list:
        # order of precedence for error checking
        if decorator.get("id") == "nonreentrant":
            ret.set_nonreentrant(decorator)

        elif decorator.get("id") == "reentrant":
            ret.set_reentrant(decorator)

        elif isinstance(decorator, vy_ast.Call):
            msg = "Decorator is not callable"
            hint = None
            if decorator.get("func.id") == "nonreentrant":
                hint = "use `@nonreentrant` with no arguments. the "
                hint += "`@nonreentrant` decorator does not accept any "
                hint += "arguments since vyper 0.4.0."
            raise StructureException(msg, decorator, hint=hint)

        elif decorator.get("id") == "raw_return":
            ret.set_raw_return(decorator)

        elif isinstance(decorator, vy_ast.Name):
            if FunctionVisibility.is_valid_value(decorator.id):
                ret.set_visibility(decorator)
            elif StateMutability.is_valid_value(decorator.id):
                ret.set_state_mutability(decorator)
            else:
                raise FunctionDeclarationException(f"Unknown decorator: {decorator.id}", decorator)

        else:
            raise StructureException("Bad decorator syntax", decorator)

    if ret.state_mutability == StateMutability.PURE and ret.nonreentrant_node is not None:
        raise StructureException(
            "Cannot use reentrancy guard on pure functions", ret.nonreentrant_node
        )

    return ret


def _parse_args(
    funcdef: vy_ast.FunctionDef, is_interface: bool = False
) -> tuple[list[PositionalArg], list[KeywordArg]]:
    argnames = set()  # for checking uniqueness
    n_total_args = len(funcdef.args.args)
    n_positional_args = n_total_args - len(funcdef.args.defaults)

    positional_args = []
    keyword_args = []

    for i, arg in enumerate(funcdef.args.args):
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
            value = funcdef.args.defaults[i - n_positional_args]
            if not check_modifiability(value, Modifiability.RUNTIME_CONSTANT):
                raise StateAccessViolation("Value must be literal or environment variable", value)
            validate_expected_type(value, type_)
            keyword_args.append(KeywordArg(argname, type_, ast_source=arg, default_value=value))

        argnames.add(argname)

    return positional_args, keyword_args


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

    typeclass = "member_function"
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

    @property
    def modifiability(self):
        return Modifiability.MODIFIABLE if self.is_modifying else Modifiability.RUNTIME_CONSTANT

    @property
    def _id(self):
        return self.name

    def __repr__(self):
        return f"{self.underlying_type} member function '{self.name}'"

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
