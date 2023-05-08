from dataclasses import dataclass
from functools import cached_property
from typing import Dict, Optional, Tuple

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, StructureException
from vyper.semantics.types import VyperType
from vyper.utils import MemoryPositions, mkalphanum

# dict from function names to signatures
FunctionSignatures = Dict[str, "FunctionSignature"]


@dataclass
class FunctionArg:
    name: str
    typ: VyperType
    ast_source: vy_ast.VyperNode


@dataclass
class FrameInfo:
    frame_start: int
    frame_size: int
    frame_vars: Dict[str, Tuple[int, VyperType]]

    @property
    def mem_used(self):
        return self.frame_size + MemoryPositions.RESERVED_MEMORY


# Function signature object
# TODO: merge with ContractFunction type
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
        self.gas_estimate = None
        self.nonreentrant_key = nonreentrant_key
        self.func_ast_code = func_ast_code
        self.is_from_json = is_from_json

        self.set_default_args()

        # frame info is metadata that will be generated during codegen.
        self.frame_info: Optional[FrameInfo] = None

    def __str__(self):
        input_name = "def " + self.name + "(" + ",".join([str(arg.typ) for arg in self.args]) + ")"
        if self.return_type:
            return input_name + " -> " + str(self.return_type) + ":"
        return input_name + ":"

    def set_frame_info(self, frame_info):
        if self.frame_info is not None:
            raise CompilerPanic("sig.frame_info already set!")
        self.frame_info = frame_info

    @cached_property
    def _ir_identifier(self) -> str:
        # we could do a bit better than this but it just needs to be unique
        visibility = "internal" if self.internal else "external"
        argz = ",".join([str(arg.typ) for arg in self.args])
        ret = f"{visibility} {self.name} ({argz})"
        return mkalphanum(ret)

    # calculate the abi signature for a given set of kwargs
    def abi_signature_for_kwargs(self, kwargs):
        args = self.base_args + kwargs
        return self.name + "(" + ",".join([arg.typ.abi_type.selector_name() for arg in args]) + ")"

    @cached_property
    def base_signature(self):
        return self.abi_signature_for_kwargs([])

    @property
    # common entry point for external function with kwargs
    def external_function_base_entry_label(self):
        assert not self.internal

        return self._ir_identifier + "_common"

    @property
    def internal_function_label(self):
        assert self.internal, "why are you doing this"

        return self._ir_identifier

    @property
    def exit_sequence_label(self):
        return self._ir_identifier + "_cleanup"

    def set_default_args(self):
        """Split base from kwargs and set member data structures"""

        args = self.func_ast_code.args

        defaults = getattr(args, "defaults", [])
        num_base_args = len(args.args) - len(defaults)

        self.base_args = self.args[:num_base_args]
        self.default_args = self.args[num_base_args:]

        # Keep all the value to assign to default parameters.
        self.default_values = dict(zip([arg.name for arg in self.default_args], defaults))

    # Get a signature from a function definition
    @classmethod
    def from_definition(
        cls,
        func_ast,  # vy_ast.FunctionDef
        global_ctx,
        interface_def=False,
        is_from_json=False,
    ):
        name = func_ast.name

        args = []
        for arg in func_ast.args.args:
            argname = arg.arg
            argtyp = global_ctx.parse_type(arg.annotation)

            args.append(FunctionArg(argname, argtyp, arg))

        mutability = "nonpayable"  # Assume nonpayable by default
        nonreentrant_key = None
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

        # Determine the return type and whether or not it's constant. Expects something
        # of the form:
        # def foo(): ...
        # def foo() -> int128: ...
        # If there is no return type, ie. it's of the form def foo(): ...
        # and NOT def foo() -> type: ..., then it's null
        return_type = None
        if func_ast.returns:
            return_type = global_ctx.parse_type(func_ast.returns)
            # sanity check: Output type must be canonicalizable
            assert return_type.abi_type.selector_name()

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

    @property
    def is_default_func(self):
        return self.name == "__default__"

    @property
    def is_init_func(self):
        return self.name == "__init__"

    @property
    def is_regular_function(self):
        return not self.is_default_func and not self.is_init_func
