import re
from dataclasses import dataclass, field
from functools import cached_property
from itertools import zip_longest
from typing import Any, Dict, List, Optional, Tuple

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.compiler.settings import Settings
from vyper.exceptions import (
    ArgumentException,
    CallViolation,
    CompilerPanic,
    ExceptionList,
    FunctionDeclarationException,
    InvalidLiteral,
    InvalidType,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
    VyperException,
)
from vyper.semantics.analysis.base import (
    FunctionVisibility,
    Modifiability,
    ModuleInfo,
    ModuleOwnership,
    StateMutability,
    VarAccess,
    VarOffset,
)
from vyper.semantics.analysis.common import NodeAccumulator
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
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
from vyper.semantics.types.user import EventT
from vyper.semantics.types.utils import type_from_abi, type_from_annotation
from vyper.utils import OrderedSet, keccak256
from vyper.warnings import Deprecation, vyper_warn


def _get_module_info(node: vy_ast.ExprNode) -> Optional[ModuleInfo]:
    """Get ModuleInfo from a node if it references a module."""
    # First try _expr_info if available (set during local analysis)
    if node._expr_info is not None and node._expr_info.module_info is not None:
        return node._expr_info.module_info

    # Fall back to namespace lookup (works before local analysis)
    if isinstance(node, vy_ast.Name):
        module_node = node.module_node
        if module_node is not None and "namespace" in module_node._metadata:
            namespace = module_node._metadata["namespace"]
            try:
                info = namespace[node.id]
                if isinstance(info, ModuleInfo):
                    return info
            except (KeyError, AttributeError):
                pass

    return None


class NodeComparer(NodeAccumulator[bool]):
    """
    Compares two AST nodes for exact structural equality.
    For module references, compares resolved module identity.
    """

    def visit(self, node: vy_ast.VyperNode, acc: bool, other: vy_ast.VyperNode) -> bool:
        # Check nodes are the same type
        if type(node) is not type(other):
            return False

        return super().visit(node, acc, other)

    def visit_Constant(self, node: vy_ast.Constant, acc: bool, other: vy_ast.Constant) -> bool:
        return node.value == other.value

    def visit_Name(self, node: vy_ast.Name, acc: bool, other: vy_ast.Name) -> bool:
        mod1 = _get_module_info(node)
        mod2 = _get_module_info(other)

        # Both are modules
        if mod1 is not None and mod2 is not None:
            return mod1.module_t is mod2.module_t

        # Both are local reference
        if mod1 is None and mod2 is None:
            return node.id == other.id

        return False

    def visit_Attribute(self, node: vy_ast.Attribute, acc: bool, other: vy_ast.Attribute) -> bool:
        return node.attr == other.attr and self.visit(node.value, acc, other.value)

    def visit_BinOp(self, node: vy_ast.BinOp, acc: bool, other: vy_ast.BinOp) -> bool:
        return (
            type(node.op) is type(other.op)
            and self.visit(node.left, acc, other.left)
            and self.visit(node.right, acc, other.right)
        )

    def visit_UnaryOp(self, node: vy_ast.UnaryOp, acc: bool, other: vy_ast.UnaryOp) -> bool:
        return type(node.op) is type(other.op) and self.visit(node.operand, acc, other.operand)

    def visit_BoolOp(self, node: vy_ast.BoolOp, acc: bool, other: vy_ast.BoolOp) -> bool:
        return (
            type(node.op) is type(other.op)
            and len(node.values) == len(other.values)
            and all(self.visit(a, acc, b) for a, b in zip(node.values, other.values))
        )

    def visit_Compare(self, node: vy_ast.Compare, acc: bool, other: vy_ast.Compare) -> bool:
        return (
            type(node.op) is type(other.op)
            and self.visit(node.left, acc, other.left)
            and self.visit(node.right, acc, other.right)
        )

    def visit_List(self, node: vy_ast.List, acc: bool, other: vy_ast.List) -> bool:
        return len(node.elements) == len(other.elements) and all(
            self.visit(a, acc, b) for a, b in zip(node.elements, other.elements)
        )

    def visit_Tuple(self, node: vy_ast.Tuple, acc: bool, other: vy_ast.Tuple) -> bool:
        return len(node.elements) == len(other.elements) and all(
            self.visit(a, acc, b) for a, b in zip(node.elements, other.elements)
        )

    def visit_Call(self, node: vy_ast.Call, acc: bool, other: vy_ast.Call) -> bool:
        return (
            self.visit(node.func, acc, other.func)
            and len(node.args) == len(other.args)
            and all(self.visit(a, acc, b) for a, b in zip(node.args, other.args))
            and len(node.keywords) == len(other.keywords)
            and all(
                kw1.arg == kw2.arg and self.visit(kw1.value, acc, kw2.value)
                for kw1, kw2 in zip(node.keywords, other.keywords)
            )
        )

    def visit_Subscript(self, node: vy_ast.Subscript, acc: bool, other: vy_ast.Subscript) -> bool:
        return self.visit(node.value, acc, other.value) and self.visit(node.slice, acc, other.slice)

    def visit_IfExp(self, node: vy_ast.IfExp, acc: bool, other: vy_ast.IfExp) -> bool:
        return (
            self.visit(node.test, acc, other.test)
            and self.visit(node.body, acc, other.body)
            and self.visit(node.orelse, acc, other.orelse)
        )


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
    default_value: vy_ast.ExprNode


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
    is_abstract : bool
        Whether this function is abstract
    nonreentrant : bool
        Whether this function is marked `@nonreentrant` or not
    is_getter : bool
        Whether this function is an automatically generated getter for a public member
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
        is_abstract: bool,
        from_interface: bool = False,
        nonreentrant: bool = False,
        do_raw_return: bool = False,
        ast_def: vy_ast.FunctionDef | vy_ast.VariableDecl | None = None,
        is_getter: bool = False,
    ) -> None:
        super().__init__()

        self.name = name
        self.positional_args = positional_args
        self.keyword_args = keyword_args
        self.return_type = return_type
        self.visibility = function_visibility
        self.mutability = state_mutability

        self.is_abstract = is_abstract

        self.nonreentrant = nonreentrant
        self.do_raw_return = do_raw_return
        self.from_interface = from_interface
        self.is_getter = is_getter

        # sanity check, nonreentrant used to be Optional[str]
        assert isinstance(self.nonreentrant, bool)

        self.ast_def = ast_def

        self._analysed = False

        # a list of internal functions this function calls.
        # to be populated during module analysis.
        # The with_overrides variant replaces called abstract functions by their override.
        self.called_functions: OrderedSet[ContractFunctionT] = OrderedSet()

        # recursively reachable from this function
        # to be populated during module analysis.
        # The with_overrides variant replaces called abstract functions by their override,
        # which might in turn reach more functions.
        self.reachable_internal_functions: OrderedSet[ContractFunctionT] | None = None

        # These kinds of functions don't get analyzed (and don't call other functions)
        if self.is_getter or self.from_interface:
            self.reachable_internal_functions = OrderedSet()

        # writes to variables from this function
        self._variable_writes: OrderedSet[VarAccess] = OrderedSet()

        # reads of variables from this function
        self._variable_reads: OrderedSet[VarAccess] = OrderedSet()

        # list of modules used (accessed state) by this function
        self._used_modules: OrderedSet[ModuleInfo] = OrderedSet()

        # events emitted by this function (populated during analysis)
        self._emitted_events: OrderedSet[EventT] = OrderedSet()

        # to be populated during codegen
        self._ir_info: Any = None
        self._function_id: Optional[int] = None

    def _addl_dict_fields(self):
        ret = {}
        ret["argument_types"] = [t.to_dict() for t in self.argument_types]
        if self.return_type is not None:
            ret["return_type"] = self.return_type.to_dict()
        else:
            ret["return_type"] = None
        return ret

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
            or any(
                f.nonreentrant for f in self.reachable_internal_functions
            )  # We shouldn't look at overrides to check if we use state
        )

    def get_used_modules(self):
        # _used_modules is populated during analysis
        return self._used_modules

    def mark_used_module(self, module_info):
        self._used_modules.add(module_info)

    def get_emitted_events(self):
        return self._emitted_events

    def mark_emitted_event(self, event: EventT):
        self._emitted_events.add(event)

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
            is_abstract=False,
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

        positional_args, keyword_args = _parse_args(funcdef, is_interface=True)

        return_type = _parse_return_type(funcdef)

        return cls(
            funcdef.name,
            positional_args,
            keyword_args,
            return_type,
            function_visibility,
            state_mutability,
            is_abstract=False,
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

        if decorators.is_abstract:
            raise FunctionDeclarationException(
                "`@abstract` decorator not allowed in interfaces", decorators.abstract_node
            )

        if decorators.override_nodes:
            raise FunctionDeclarationException(
                "`@override` decorator not allowed in interfaces", decorators.override_nodes[0]
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

        positional_args, keyword_args = _parse_args(funcdef, is_interface=True)

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
            is_abstract=False,
            from_interface=True,
            nonreentrant=False,
            ast_def=funcdef,
        )

    @classmethod
    def from_FunctionDef(
        cls, funcdef: vy_ast.FunctionDef, is_getter: bool = False
    ) -> "ContractFunctionT":
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

        is_abstract = decorators.is_abstract

        if function_visibility != FunctionVisibility.INTERNAL:
            if is_abstract:
                raise FunctionDeclarationException(
                    f"@abstract decorator is not allowed on {function_visibility.value} functions",
                    decorators.abstract_node,
                )

            if decorators.override_nodes:
                raise FunctionDeclarationException(
                    f"@override decorator is not allowed on {function_visibility.value} functions",
                    decorators.override_nodes[0],
                )

        positional_args, keyword_args = _parse_args(funcdef, is_abstract=is_abstract)

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

        self = cls(
            funcdef.name,
            positional_args,
            keyword_args,
            return_type,
            function_visibility,
            decorators.state_mutability,
            is_abstract,
            from_interface=False,
            nonreentrant=nonreentrant,
            do_raw_return=decorators.raw_return,
            ast_def=funcdef,
            is_getter=is_getter,
        )

        # Validate overrides and set `overridden_by` on corresponding abstract methods
        for name in decorators.override_nodes:
            from vyper.semantics.namespace import Namespace

            try:
                module_info = Namespace.context.get()[name.id]
            except KeyError:
                # Module is not imported, error will be reported elsewhere
                continue

            if not isinstance(module_info, ModuleInfo):
                raise FunctionDeclarationException(f"`{name.id}` is not a module", name)

            if module_info.ownership != ModuleOwnership.INITIALIZES:
                msg = f"Cannot override method from `{module_info.alias}`"
                msg += " - module is not initialized"
                hint = f"add `initializes: {module_info.alias}` "
                hint += "as a top-level statement to your contract"
                raise FunctionDeclarationException(msg, funcdef, hint=hint)

            abstract_t = module_info.module_t.functions.get(funcdef.name)
            if abstract_t is None:
                msg = f"Cannot override `{funcdef.name}` from `{module_info.alias}`"
                msg += " - method does not exist"
                lev_hint = get_levenshtein_error_suggestions(
                    funcdef.name, module_info.module_t.functions, 0.3
                )
                raise FunctionDeclarationException(msg, funcdef, hint=lev_hint)

            if not abstract_t.is_abstract:
                msg = f"Cannot override `{funcdef.name}` from `{module_info.alias}`"
                msg += " - method is not abstract"
                hint = "only abstract methods can be overridden"
                raise FunctionDeclarationException(msg, funcdef, hint=hint)

            if hasattr(abstract_t, "_overridden_by"):
                raise FunctionDeclarationException(
                    f"Method `{funcdef.name}` from `{module_info.alias}` is already overridden",
                    funcdef,
                    hint="each abstract method can only be overridden once",
                )

            abstract_t.set_overridden_by(self)

        return self

    def set_reentrancy_key_position(self, position: VarOffset) -> None:
        if hasattr(self, "reentrancy_key_position"):
            raise CompilerPanic("Position was already assigned")
        if not self.nonreentrant:
            raise CompilerPanic(f"Not nonreentrant {self}", self.ast_def)

        self.reentrancy_key_position = position

    def set_overridden_by(self, func_t: "ContractFunctionT") -> None:
        assert not hasattr(self, "_overridden_by")
        self._overridden_by = func_t

    @property
    def overridden_by(self) -> "ContractFunctionT":
        if not hasattr(self, "_overridden_by"):
            raise FunctionDeclarationException("Abstract function was not overridden", self.ast_def)
        return self._overridden_by

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
            is_abstract=False,
            from_interface=False,
            function_visibility=FunctionVisibility.EXTERNAL,
            state_mutability=StateMutability.VIEW,
            ast_def=node,
            is_getter=True,
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
            if not btyp.is_subtype_of(atyp):
                return False

        # Return type should be covariant, not contravariant!
        # It should be:
        # if return_type and not return_type.is_subtype_of(other_return_type):  # type: ignore
        # This is currently done to allow things like IERC20's name field to be implemented by
        # strings of any length. `String[0]` is thus able to be implemented by a `String[20]`.
        # TODO: Once we have a system which removes the need for this hack, change it
        if return_type and not other_return_type.is_subtype_of(return_type):  # type: ignore
            return False

        return self.mutability == other.mutability

    def override_discrepancies(self, abstract_t: "ContractFunctionT") -> ExceptionList:
        assert self.is_internal
        assert abstract_t.is_internal
        assert abstract_t.is_abstract

        parameters_override = self.arguments
        return_type_override = self.return_type

        parameters_abstract = abstract_t.arguments
        return_type_abstract = abstract_t.return_type

        discrepancies: ExceptionList = ExceptionList()

        def pretty_param(param: _FunctionArg) -> str:
            return f"`{param.name}: {param.typ._id}`"

        def parameter_override_discrepancy(
            p_override: _FunctionArg, p_abstract: _FunctionArg | None
        ) -> VyperException | None:
            if p_abstract is None:
                if isinstance(p_override, KeywordArg):
                    return None
                else:
                    return FunctionDeclarationException(
                        f"Override has mandatory parameter {pretty_param(p_override)} "
                        "not present in the abstract method.",
                        p_override.ast_source,
                        hint="Remove the extra parameter, or add a default value",
                    )

            def default_values_match() -> bool:
                if isinstance(p_abstract, KeywordArg):
                    if not isinstance(p_override, KeywordArg):
                        # Default cannot be overridden by non-default
                        return False

                    if isinstance(p_abstract.default_value, vy_ast.Ellipsis):
                        # `...` default can be overridden by any default
                        return True

                    # other defaults must match exactly, 1 + 1 cannot be overridden by 2
                    return NodeComparer().visit(
                        p_abstract.default_value, False, p_override.default_value
                    )
                else:
                    # Non-default can be overridden by both default and non-default
                    return True

            if (
                p_override.name == p_abstract.name
                and p_override.typ.is_supertype_of(p_abstract.typ)
                and default_values_match()
            ):
                return None
            else:
                return FunctionDeclarationException(
                    "Override parameter mismatch: "
                    f"Got {pretty_param(p_override)}, "
                    f"but expected {pretty_param(p_abstract)} (or stricter)",
                    p_override.ast_source,
                    p_abstract.ast_source,
                )

        # Parameter validation

        if len(parameters_override) < len(parameters_abstract):
            discrepancies.append(
                FunctionDeclarationException(
                    "Override does not have the correct number of parameters. Has "
                    f"{len(parameters_override)}, should have {len(parameters_abstract)} (or more)",
                    self.ast_def,
                    abstract_t.ast_def,
                )
            )
        else:
            for p_override, p_abstract in zip_longest(parameters_override, parameters_abstract):
                discrepancy = parameter_override_discrepancy(p_override, p_abstract)

                if discrepancy is not None:
                    discrepancies.append(discrepancy)

        # Return type validation

        if return_type_abstract:
            if return_type_override:
                if not return_type_override.is_subtype_of(return_type_abstract):
                    discrepancies.append(
                        FunctionDeclarationException(
                            "Override return type mismatch: "
                            f"Got {return_type_override}, but expected {return_type_abstract}",
                            self.ast_def,
                            abstract_t.ast_def,
                        )
                    )
            else:
                discrepancies.append(
                    FunctionDeclarationException(
                        "Override return type mismatch: "
                        f"Got no return type, but expected {return_type_abstract}",
                        self.ast_def,
                        abstract_t.ast_def,
                    )
                )
        else:
            if return_type_override:
                discrepancies.append(
                    FunctionDeclarationException(
                        "Override return type mismatch: "
                        f"Got {return_type_override}, but expected no return type",
                        self.ast_def,
                        abstract_t.ast_def,
                    )
                )

        # Mutability validation

        if self.mutability > abstract_t.mutability:
            # There is nothing stricter than @pure
            or_stricter = " (or stricter)" if abstract_t.mutability != StateMutability.PURE else ""

            discrepancies.append(
                FunctionDeclarationException(
                    "Override mutability mismatch: "
                    f"Got {self.mutability}, but expected {abstract_t.mutability}{or_stricter}",
                    self.ast_def,
                    abstract_t.ast_def,
                )
            )

        # Reentrancy validation

        if self.nonreentrant != abstract_t.nonreentrant:

            def _is(b: bool) -> str:
                return "is" if b else "isn't"

            action = "add a" if abstract_t.nonreentrant else "remove the"
            discrepancies.append(
                FunctionDeclarationException(
                    f"Override reentrancy mismatch: Override {_is(self.nonreentrant)} non-reentrant"
                    f", unlike the method it is overriding.",
                    self.ast_def,
                    abstract_t.ast_def,
                    hint=f"{action} @nonreentrant decorator",
                )
            )

        return discrepancies

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
    funcdef: vy_ast.FunctionDef
    override_nodes: List[vy_ast.Name] = field(default_factory=lambda: [])
    visibility_node: Optional[vy_ast.Name] = None
    state_mutability_node: Optional[vy_ast.Name] = None
    nonreentrant_node: Optional[vy_ast.Name] = None
    raw_return_node: Optional[vy_ast.Name] = None
    reentrant_node: Optional[vy_ast.Name] = None
    abstract_node: Optional[vy_ast.Name] = None

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

    def set_abstract(self, decorator_node: vy_ast.Name):
        if self.abstract_node is not None:
            raise StructureException(
                "abstract decorator is already set", self.abstract_node, decorator_node
            )
        self.abstract_node = decorator_node

    @property
    def is_abstract(self) -> bool:
        return self.abstract_node is not None

    def add_override(self, decorator_node: vy_ast.Name | vy_ast.Call):
        if isinstance(decorator_node, vy_ast.Name):
            # TODO: Add a smart hint that takes into account
            # which modules are initialized with a method of the same name
            raise StructureException(
                "override decorator needs a parameter"
                " (the module containing the method to override)",
                decorator_node,
            )
        num_args = len(decorator_node.args)
        if num_args != 1:
            # TODO: Add a smart hint that shows multiple consecutive decorators
            raise StructureException(
                f"override decorator takes a single parameter ({num_args} given)", decorator_node
            )

        self.override_nodes.append(decorator_node.args[0])

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

        def unknown_decorator(name: str) -> FunctionDeclarationException:
            return FunctionDeclarationException(
                f"Unknown decorator: {name}", decorator  # noqa: B023
            )

        # Decorators without argument clause: `@something`
        if isinstance(decorator, vy_ast.Name):
            if decorator.id == "nonreentrant":
                ret.set_nonreentrant(decorator)
            elif decorator.id == "reentrant":
                ret.set_reentrant(decorator)
            elif decorator.id == "raw_return":
                ret.set_raw_return(decorator)
            elif decorator.id == "abstract":
                ret.set_abstract(decorator)
            elif decorator.id == "override":
                # Delegate error reporting to add_override
                ret.add_override(decorator)
            elif FunctionVisibility.is_valid_value(decorator.id):
                ret.set_visibility(decorator)
            elif StateMutability.is_valid_value(decorator.id):
                ret.set_state_mutability(decorator)
            else:
                raise unknown_decorator(decorator.id)

        # Decorators with argument clause: `@something()`
        elif isinstance(decorator, vy_ast.Call):
            decorators_without_parameters = (
                ["reentrant", "nonreentrant", "raw_return"]
                + FunctionVisibility.values()
                + StateMutability.values()
            )

            assert isinstance(decorator.func, vy_ast.Name)

            if decorator.func.id == "override":
                ret.add_override(decorator)

            elif decorator.func.id in decorators_without_parameters:
                msg = "Decorator does not take parameters"

                hint = f"use `@{decorator.func.id}` with no arguments."
                if decorator.func.id == "nonreentrant":
                    hint += "the `@nonreentrant` decorator does not accept any "
                    hint += "arguments since vyper 0.4.0."
                raise StructureException(msg, decorator, hint=hint)
            else:
                raise unknown_decorator(decorator.func.id)

        else:
            raise StructureException("Bad decorator syntax", decorator)

    if ret.state_mutability == StateMutability.PURE and ret.nonreentrant_node is not None:
        raise StructureException(
            "Cannot use reentrancy guard on pure functions", ret.nonreentrant_node
        )

    return ret


def _parse_args(
    funcdef: vy_ast.FunctionDef, is_interface: bool = False, is_abstract: bool = False
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
            if is_interface and not isinstance(value, vy_ast.Ellipsis):
                vyper_warn(
                    Deprecation(
                        "Please use `...` as default value. (Values "
                        "for default parameters in interfaces have always been ignored.)",
                        value,
                    )
                )

            if isinstance(value, vy_ast.Ellipsis) and not (is_interface or is_abstract):
                raise InvalidLiteral(
                    "`...` is only allowed as a default value in interfaces"
                    " and for abstract methods.",
                    value,
                )

            if not check_modifiability(value, Modifiability.RUNTIME_CONSTANT):
                raise StateAccessViolation("Value must be literal or environment variable", value)

            if not isinstance(value, vy_ast.Ellipsis):
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
