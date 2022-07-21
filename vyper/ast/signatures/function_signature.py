import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from vyper import ast as vy_ast
from vyper.address_space import MEMORY
from vyper.codegen.ir_node import Encoding
from vyper.codegen.types import NodeType
from vyper.exceptions import StructureException
from vyper.utils import MemoryPositions, cached_property, mkalphanum

# dict from function names to signatures
FunctionSignatures = Dict[str, "FunctionSignature"]


# Function variable
# TODO move to context.py
# TODO use dataclass
class VariableRecord:
    def __init__(  # type: ignore
        self,
        name,
        pos,
        typ,
        mutable,
        encoding=Encoding.VYPER,
        location=MEMORY,
        blockscopes=None,
        defined_at=None,  # note: dead variable
        is_internal=False,
        is_immutable=False,
        data_offset: Optional[int] = None,
    ):
        self.name = name
        self.pos = pos
        self.typ = typ
        self.mutable = mutable
        self.location = location
        self.encoding = encoding
        self.blockscopes = [] if blockscopes is None else blockscopes
        self.defined_at = defined_at  # source code location variable record was defined.
        self.is_internal = is_internal
        self.is_immutable = is_immutable
        self.data_offset = data_offset  # location in data section

    def __repr__(self):
        ret = vars(self)
        ret["allocated"] = self.size * 32
        return f"VariableRecord(f{ret})"

    @property
    def size(self):
        if hasattr(self.typ, "size_in_bytes"):
            # temporary requirement to support both new and old type objects
            # we divide by 32 here because the returned value is denominated
            # in "slots" of 32 bytes each
            # CMC 20211023 revisit this divide-by-32.
            return math.ceil(self.typ.size_in_bytes / 32)
        return math.ceil(self.typ.memory_bytes_required / 32)


@dataclass
class FunctionArg:
    name: str
    typ: NodeType
    ast_source: vy_ast.VyperNode


@dataclass
class FrameInfo:
    frame_start: int
    frame_size: int
    frame_vars: Dict[str, Tuple[int, NodeType]]

    @property
    def mem_used(self):
        return self.frame_size + MemoryPositions.RESERVED_MEMORY


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
        constant_override=False,  # CMC 20210907 what does this do?
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
