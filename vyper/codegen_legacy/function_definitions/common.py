from dataclasses import dataclass
from typing import Optional

from vyper.codegen_legacy.context import Constancy, Context
from vyper.codegen_legacy.ir_node import IRnode
from vyper.codegen_legacy.memory_allocator import MemoryAllocator
from vyper.codegen_shared.function_info import (
    EntryPointInfo,
    _FuncIRInfo,
    init_ir_info,
)
from vyper.evm.opcodes import version_check
from vyper.semantics.types import VyperType
from vyper.semantics.types.function import ContractFunctionT, StateMutability
from vyper.semantics.types.module import ModuleT
from vyper.utils import MemoryPositions

# Re-export shared types for downstream consumers
__all__ = ["EntryPointInfo", "_FuncIRInfo", "FrameInfo", "init_ir_info"]


@dataclass
class FrameInfo:
    frame_start: int
    frame_size: int
    frame_vars: dict[str, tuple[int, VyperType]]

    @property
    def mem_used(self):
        return self.frame_size + MemoryPositions.RESERVED_MEMORY


@dataclass
class ExternalFuncIR:
    entry_points: dict[str, EntryPointInfo]  # map from abi sigs to entry points
    common_ir: IRnode  # the "common" code for the function


@dataclass
class InternalFuncIR:
    func_ir: IRnode  # the code for the function


def initialize_context(
    func_t: ContractFunctionT, module_ctx: ModuleT, is_ctor_context: bool = False
):
    init_ir_info(func_t)

    # calculate starting frame
    callees = func_t.called_functions
    # we start our function frame from the largest callee frame
    max_callee_frame_size = 0
    for c_func_t in callees:
        assert not c_func_t.is_abstract
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
