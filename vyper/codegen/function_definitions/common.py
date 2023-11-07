from dataclasses import dataclass
from functools import cached_property
from typing import Optional

import vyper.ast as vy_ast
from vyper.codegen.context import Constancy, Context
from vyper.codegen.core import check_single_exit
from vyper.codegen.function_definitions.external_function import generate_ir_for_external_function
from vyper.codegen.function_definitions.internal_function import generate_ir_for_internal_function
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen.memory_allocator import MemoryAllocator
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import VyperType
from vyper.semantics.types.function import ContractFunctionT
from vyper.utils import MemoryPositions, calc_mem_gas, mkalphanum


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

    @property
    def visibility(self):
        return "internal" if self.func_t.is_internal else "external"

    @property
    def exit_sequence_label(self) -> str:
        return self.ir_identifier + "_cleanup"

    @cached_property
    def ir_identifier(self) -> str:
        argz = ",".join([str(argtyp) for argtyp in self.func_t.argument_types])
        return mkalphanum(f"{self.visibility} {self.func_t.name} ({argz})")

    def set_frame_info(self, frame_info: FrameInfo) -> None:
        if self.frame_info is not None:
            raise CompilerPanic(f"frame_info already set for {self.func_t}!")
        self.frame_info = frame_info

    @property
    # common entry point for external function with kwargs
    def external_function_base_entry_label(self) -> str:
        assert not self.func_t.is_internal, "uh oh, should be external"
        return self.ir_identifier + "_common"

    def internal_function_label(self, is_ctor_context: bool = False) -> str:
        assert self.func_t.is_internal, "uh oh, should be internal"
        suffix = "_deploy" if is_ctor_context else "_runtime"
        return self.ir_identifier + suffix


class FuncIR:
    pass


@dataclass
class EntryPointInfo:
    func_t: ContractFunctionT
    min_calldatasize: int  # the min calldata required for this entry point
    ir_node: IRnode  # the ir for this entry point

    def __post_init__(self):
        # ABI v2 property guaranteed by the spec.
        # https://docs.soliditylang.org/en/v0.8.21/abi-spec.html#formal-specification-of-the-encoding states:  # noqa: E501
        # > Note that for any X, len(enc(X)) is a multiple of 32.
        assert self.min_calldatasize >= 4
        assert (self.min_calldatasize - 4) % 32 == 0


@dataclass
class ExternalFuncIR(FuncIR):
    entry_points: dict[str, EntryPointInfo]  # map from abi sigs to entry points
    common_ir: IRnode  # the "common" code for the function


@dataclass
class InternalFuncIR(FuncIR):
    func_ir: IRnode  # the code for the function


# TODO: should split this into external and internal ir generation?
def generate_ir_for_function(
    code: vy_ast.FunctionDef, global_ctx: GlobalContext, is_ctor_context: bool = False
) -> FuncIR:
    """
    Parse a function and produce IR code for the function, includes:
        - Signature method if statement
        - Argument handling
        - Clamping and copying of arguments
        - Function body
    """
    func_t = code._metadata["type"]

    # generate _FuncIRInfo
    func_t._ir_info = _FuncIRInfo(func_t)

    # Validate return statements.
    # XXX: This should really be in semantics pass.
    check_single_exit(code)

    callees = func_t.called_functions

    # we start our function frame from the largest callee frame
    max_callee_frame_size = 0
    for c_func_t in callees:
        frame_info = c_func_t._ir_info.frame_info
        max_callee_frame_size = max(max_callee_frame_size, frame_info.frame_size)

    allocate_start = max_callee_frame_size + MemoryPositions.RESERVED_MEMORY

    memory_allocator = MemoryAllocator(allocate_start)

    context = Context(
        vars_=None,
        global_ctx=global_ctx,
        memory_allocator=memory_allocator,
        constancy=Constancy.Mutable if func_t.is_mutable else Constancy.Constant,
        func_t=func_t,
        is_ctor_context=is_ctor_context,
    )

    if func_t.is_internal:
        ret: FuncIR = InternalFuncIR(generate_ir_for_internal_function(code, func_t, context))
        func_t._ir_info.gas_estimate = ret.func_ir.gas  # type: ignore
    else:
        kwarg_handlers, common = generate_ir_for_external_function(code, func_t, context)
        entry_points = {
            k: EntryPointInfo(func_t, mincalldatasize, ir_node)
            for k, (mincalldatasize, ir_node) in kwarg_handlers.items()
        }
        ret = ExternalFuncIR(entry_points, common)
        # note: this ignores the cost of traversing selector table
        func_t._ir_info.gas_estimate = ret.common_ir.gas

    frame_size = context.memory_allocator.size_of_mem - MemoryPositions.RESERVED_MEMORY

    frame_info = FrameInfo(allocate_start, frame_size, context.vars)

    # XXX: when can this happen?
    if func_t._ir_info.frame_info is None:
        func_t._ir_info.set_frame_info(frame_info)
    else:
        assert frame_info == func_t._ir_info.frame_info

    if not func_t.is_internal:
        # adjust gas estimate to include cost of mem expansion
        # frame_size of external function includes all private functions called
        # (note: internal functions do not need to adjust gas estimate since
        mem_expansion_cost = calc_mem_gas(func_t._ir_info.frame_info.mem_used)  # type: ignore
        ret.common_ir.add_gas_estimate += mem_expansion_cost  # type: ignore

    return ret
