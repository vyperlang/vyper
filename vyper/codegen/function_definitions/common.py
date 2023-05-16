# can't use from [module] import [object] because it breaks mocks in testing
from typing import Dict

import vyper.ast as vy_ast
from vyper.codegen.context import Constancy, Context
from vyper.codegen.core import check_single_exit, getpos
from vyper.codegen.function_definitions.external_function import generate_ir_for_external_function
from vyper.codegen.function_definitions.internal_function import generate_ir_for_internal_function
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen.memory_allocator import MemoryAllocator
from vyper.semantics.types.function import ContractFunctionT, FrameInfo
from vyper.utils import MemoryPositions, calc_mem_gas


def generate_ir_for_function(
    code: vy_ast.FunctionDef,
    func_ts: Dict[str, Dict[str, ContractFunctionT]],  # all ContractFunctionT in all namespaces
    global_ctx: GlobalContext,
    skip_nonpayable_check: bool,
    is_ctor_context: bool = False,
) -> IRnode:
    """
    Parse a function and produce IR code for the function, includes:
        - Signature method if statement
        - Argument handling
        - Clamping and copying of arguments
        - Function body
    """
    func_t = code._metadata["type"]

    # Validate return statements.
    check_single_exit(code)

    callees = func_t.called_functions

    # we start our function frame from the largest callee frame
    max_callee_frame_size = 0
    for c in callees:
        frame_info = func_ts["self"][c.name].ir_info.frame_info
        assert frame_info is not None  # make mypy happy
        max_callee_frame_size = max(max_callee_frame_size, frame_info.frame_size)

    allocate_start = max_callee_frame_size + MemoryPositions.RESERVED_MEMORY

    memory_allocator = MemoryAllocator(allocate_start)

    context = Context(
        vars_=None,
        global_ctx=global_ctx,
        func_ts=func_ts,
        memory_allocator=memory_allocator,
        constancy=Constancy.Mutable if func_t.is_mutable else Constancy.Constant,
        func_t=func_t,
        is_ctor_context=is_ctor_context,
    )

    if func_t.is_internal:
        assert skip_nonpayable_check is False
        o = generate_ir_for_internal_function(code, func_t, context)
    else:
        if func_t.is_payable:
            assert skip_nonpayable_check is False  # nonsense
        o = generate_ir_for_external_function(code, func_t, context, skip_nonpayable_check)

    o.source_pos = getpos(code)

    frame_size = context.memory_allocator.size_of_mem - MemoryPositions.RESERVED_MEMORY

    frame_info = FrameInfo(allocate_start, frame_size, context.vars)

    if func_t.ir_info.frame_info is None:
        func_t.set_frame_info(frame_info)
    else:
        assert frame_info == func_t.ir_info.frame_info

    if not func_t.is_internal:
        # adjust gas estimate to include cost of mem expansion
        # frame_size of external function includes all private functions called
        # (note: internal functions do not need to adjust gas estimate since
        # it is already accounted for by the caller.)
        assert func_t.ir_info.frame_info is not None  # mypy hint
        o.add_gas_estimate += calc_mem_gas(func_t.ir_info.frame_info.mem_used)

    func_t.gas_estimate = o.gas

    return o
