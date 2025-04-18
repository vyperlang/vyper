from dataclasses import dataclass
from functools import cached_property
from typing import Optional

from vyper.codegen.context import Constancy, Context
from vyper.codegen.ir_node import IRnode
from vyper.codegen.memory_allocator import MemoryAllocator
from vyper.evm.opcodes import version_check
from vyper.semantics.types import VyperType
from vyper.semantics.types.function import ContractFunctionT, StateMutability
from vyper.semantics.types.module import ModuleT
from vyper.utils import MemoryPositions


@dataclass
class FrameInfo:
    frame_start: int
    frame_size: int
    frame_vars: dict[str, tuple[int, VyperType]]

    @property
    def mem_used(self):
        return self.frame_size + MemoryPositions.RESERVED_MEMORY


@dataclass
class _FuncIRInfo:
    func_t: ContractFunctionT
    gas_estimate: Optional[int] = None
    frame_info: Optional[FrameInfo] = None
    func_ir: Optional["InternalFuncIR"] = None

    @property
    def visibility(self):
        return "internal" if self.func_t.is_internal else "external"

    @property
    def exit_sequence_label(self) -> str:
        return self.ir_identifier + "_cleanup"

    @cached_property
    def ir_identifier(self) -> str:
        argz = ",".join([str(argtyp) for argtyp in self.func_t.argument_types])

        name = self.func_t.name
        function_id = self.func_t._function_id
        assert function_id is not None

        # include module id in the ir identifier to disambiguate functions
        # with the same name but which come from different modules
        return f"{self.visibility} {function_id} {name}({argz})"

    def set_frame_info(self, frame_info: FrameInfo) -> None:
        # XXX: when can this happen?
        if self.frame_info is not None:
            assert frame_info == self.frame_info
        else:
            self.frame_info = frame_info

    def set_func_ir(self, func_ir: "InternalFuncIR") -> None:
        assert self.func_t.is_internal or self.func_t.is_deploy
        self.func_ir = func_ir

    @property
    # common entry point for external function with kwargs
    def external_function_base_entry_label(self) -> str:
        assert not self.func_t.is_internal, "uh oh, should be external"
        return self.ir_identifier + "_common"

    def internal_function_label(self, is_ctor_context: bool = False) -> str:
        f = self.func_t
        assert f.is_internal or f.is_constructor, "uh oh, should be internal"

        if f.is_constructor:
            # sanity check - imported init functions only callable from main init
            assert is_ctor_context

        suffix = "_deploy" if is_ctor_context else "_runtime"
        return self.ir_identifier + suffix


@dataclass
class EntryPointInfo:
    func_t: ContractFunctionT
    min_calldatasize: int  # the min calldata required for this entry point
    ir_node: IRnode  # the ir for this entry point

    def __post_init__(self):
        # sanity check ABI v2 properties guaranteed by the spec.
        # https://docs.soliditylang.org/en/v0.8.21/abi-spec.html#formal-specification-of-the-encoding states:  # noqa: E501
        # > Note that for any X, len(enc(X)) is a multiple of 32.
        assert self.min_calldatasize >= 4
        assert (self.min_calldatasize - 4) % 32 == 0


@dataclass
class ExternalFuncIR:
    entry_points: dict[str, EntryPointInfo]  # map from abi sigs to entry points
    common_ir: IRnode  # the "common" code for the function


@dataclass
class InternalFuncIR:
    func_ir: IRnode  # the code for the function


def init_ir_info(func_t: ContractFunctionT):
    # initialize IRInfo on the function
    func_t._ir_info = _FuncIRInfo(func_t)


def initialize_context(
    func_t: ContractFunctionT, module_ctx: ModuleT, is_ctor_context: bool = False
):
    init_ir_info(func_t)

    # calculate starting frame
    callees = func_t.called_functions
    # we start our function frame from the largest callee frame
    max_callee_frame_size = 0
    for c_func_t in callees:
        frame_info = c_func_t._ir_info.frame_info
        max_callee_frame_size = max(max_callee_frame_size, frame_info.frame_size)

    allocate_start = max_callee_frame_size + MemoryPositions.RESERVED_MEMORY

    memory_allocator = MemoryAllocator(allocate_start)

    return Context(
        vars_=None,
        module_ctx=module_ctx,
        memory_allocator=memory_allocator,
        constancy=Constancy.Mutable if func_t.is_mutable else Constancy.Constant,
        func_t=func_t,
        is_ctor_context=is_ctor_context,
    )


def tag_frame_info(func_t, context):
    frame_size = context.memory_allocator.size_of_mem - MemoryPositions.RESERVED_MEMORY
    frame_start = context.starting_memory

    frame_info = FrameInfo(frame_start, frame_size, context.vars)
    func_t._ir_info.set_frame_info(frame_info)

    return frame_info


def get_nonreentrant_lock(func_t):
    if not func_t.nonreentrant:
        return ["pass"], ["pass"]

    nkey = func_t.reentrancy_key_position.position

    LOAD, STORE = "sload", "sstore"
    if version_check(begin="cancun"):
        LOAD, STORE = "tload", "tstore"
        # for tload/tstore we don't need to care about net gas metering,
        # choose small constants (e.g. 0 can be replaced by PUSH0)
        final_value, temp_value = 0, 1
    else:
        # any nonzero values can work here (see pricing as of net gas
        # metering); these values are chosen so that downgrading to the
        # 0,1 scheme (if it is somehow necessary) is safe.
        final_value, temp_value = 3, 2

    check_notset = ["assert", ["ne", temp_value, [LOAD, nkey]]]

    if func_t.mutability == StateMutability.VIEW:
        return [check_notset], [["seq"]]

    else:
        assert func_t.mutability >= StateMutability.NONPAYABLE  # sanity
        pre = ["seq", check_notset, [STORE, nkey, temp_value]]
        post = [STORE, nkey, final_value]
        return [pre], [post]
