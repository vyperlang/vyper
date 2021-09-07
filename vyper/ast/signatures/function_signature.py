import math
from collections import Counter

from vyper import ast as vy_ast
from vyper.exceptions import FunctionDeclarationException, StructureException
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import check_single_exit, getpos
from vyper.old_codegen.types import (
    NodeType,
    ByteArrayLike,
    TupleType,
    canonicalize_type,
    get_size_of_type,
    parse_type,
)
from vyper.utils import fourbytes_to_int, keccak256, mkalphanum
from functools import cached_property


# Function variable
# TODO move to context.py
class VariableRecord:
    def __init__(
        self,
        name,
        pos,
        typ,
        mutable,
        *,
        location="memory",
        blockscopes=None,
        defined_at=None,
        is_internal=False,
    ):
        self.name = name
        self.pos = pos
        self.typ = typ
        self.mutable = mutable
        self.location = location
        self.blockscopes = [] if blockscopes is None else blockscopes
        self.defined_at = defined_at  # source code location variable record was defined.
        self.is_internal = is_internal

    @property
    def size(self):
        if hasattr(self.typ, "size_in_bytes"):
            # temporary requirement to support both new and old type objects
            # we divide by 32 here because the returned value is denominated
            # in "slots" of 32 bytes each
            return math.ceil(self.typ.size_in_bytes / 32)
        return get_size_of_type(self.typ)


class ContractRecord(VariableRecord):
    def __init__(self, *args):
        super(ContractRecord, self).__init__(*args)


@dataclass
class FunctionArg:
    name: str
    typ: NodeType


# Function signature object
class FunctionSignature:
    def __init__(
        self,
        name,
        args,
        return_type,
        mutability,
        internal,
        nonreentrant_key,
        func_ast_code,
        is_from_json,
    ):
        self.name = name
        self.args = args
        self.return_type = return_type
        self.mutability = mutability
        self.internal = internal
        self.gas = None
        self.nonreentrant_key = nonreentrant_key
        self.func_ast_code = func_ast_code
        self.is_from_json = is_from_json

        self.set_default_args()

    def __str__(self):
        input_name = "def " + self.name + "(" + ",".join([str(arg.typ) for arg in self.args]) + ")"
        if self.output_type:
            return input_name + " -> " + str(self.output_type) + ":"
        return input_name + ":"

    def _abi_signature(self, args):
        return self.func_name + "(" + ",".join([canonicalize_type(arg.typ) for arg in args]) + ")"

    @cached_property
    def all_kwarg_sigs(self) -> List[str]:
        assert not self.internal, "abi_signatures only make sense for external functions"
        ret = []
        argz = self.base_args.copy()

        ret.append(self._abi_signature(argz))

        for arg in self.default_args:
            argz.append(arg)
            ret.append(self._abi_signature(argz))

        return ret

    @property
    def internal_function_label(self):
        assert self.internal, "why are you doing this"

        # we could do a bit better than this but it just needs to be unique
        return mkalphanum(str(self))

    @property
    def exit_sequence_label(self):
        return mkalphanum(str(self)) + "_cleanup"

    def set_default_args(self):
        """Split base from kwargs and set member data structures"""

        args = self.func_ast_code.args

        defaults = getattr(args, "defaults", [])
        num_base_args = len(args) - len(defaults)

        self.base_args = self.args[:num_base_args]
        self.default_args = self.args[num_base_args:]

        # Keep all the value to assign to default parameters.
        self.default_values = dict(
            zip([arg.name for arg in self.default_args], args.defaults)
        )

    # Get a signature from a function definition
    @classmethod
    def from_definition(
        cls,
        func_ast, # vy_ast.FunctionDef
        sigs=None, # TODO replace sigs and custom_structs with GlobalContext?
        custom_structs=None,
        interface_def=False,
        constant_override=False, # CMC 20210907 what does this do?
        is_from_json=False,
    ):
        if custom_structs is None:
            custom_structs = {}

        name = code.name

        args = []
        for arg in func_ast.args.args:
            argname = arg.arg
            argtyp = parse_type(arg.annotation, None, sigs, custom_structs=custom_structs,)

            args.append(FunctionArg(argname, argtyp))

        mutability = "nonpayable"  # Assume nonpayable by default
        nonreentrant_key = ""
        is_internal = None

        # Update function properties from decorators
        # NOTE: Can't import enums here because of circular import
        for dec in func_ast.decorator_list:
            if isinstance(dec, vy_ast.Name) and dec.id in ("payable", "view", "pure"):
                mutability = dec.id
            elif isinstance(dec, vy_ast.Name) and dec.id == "internal":
                is_internal = True
            elif isinstance(dec, vy_ast.Name) and dec.id == "external":
                is_internal = False
            elif isinstance(dec, vy_ast.Call) and dec.func.id == "nonreentrant":
                nonreentrant_key = dec.args[0].s

        if constant_override:
            # In case this override is abused, match previous behavior
            if mutability == "payable":
                raise StructureException(f"Function {name} cannot be both constant and payable.")
            mutability = "view"

        # Determine the return type and whether or not it's constant. Expects something
        # of the form:
        # def foo(): ...
        # def foo() -> int128: ...
        # If there is no return type, ie. it's of the form def foo(): ...
        # and NOT def foo() -> type: ..., then it's null
        return_type = None
        if func_ast.returns:
            return_type = parse_type(func_ast.returns, None, sigs, custom_structs=custom_structs,)
            # sanity check: Output type must be canonicalizable
            assert canonicalize_type(return_type)

        return cls(
            name,
            args,
            return_type,
            mutability,
            is_internal,
            nonreentrant_key,
            func_ast,
            is_from_json,
        )

    @classmethod
    def lookup_internal_function(cls, method_name, args_lll, context):
        """
        Using a list of args, find the internal method to use, and
        the kwargs which need to be filled in by the compiler
        """
        def _check(cond, s = "Unreachable"):
            if not cond:
                raise CompilerPanic(s)

        for sig in context.sigs['self']:
            if sig.name != method_name:
                continue

            _check(sig.internal) # sanity check
            # should have been caught during type checking, sanity check anyway
            _check(len(sig.base_args) <= len(args_lll) <= len(sig.args))

            # more sanity check, that the types match
            _check(all(l.typ == r.typ for l, r in zip(args_lll, sig.args)))

            num_provided_args = len(args_lll)
            total_args = len(sig.args)
            num_kwargs = len(sig.kwargs)
            args_needed = total_args - num_provided

            kw_vals = sig.kwarg_values.items()[:num_kwargs - args_needed]

            return sig, kw_vals

        _check(False)

    def is_default_func(self):
        return self.name == "__default__"

    def is_init_func(self):
        return self.name == "__init__"
