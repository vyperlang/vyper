# can't use from [module] import [object] because it breaks mocks in testing
import copy
from typing import Dict, Tuple

import vyper.ast as vy_ast
from vyper.ast.signatures import FunctionSignature
from vyper.codegen.context import Constancy, Context
from vyper.codegen.core import check_single_exit, getpos
from vyper.codegen.function_definitions.external_function import generate_ir_for_external_function
from vyper.codegen.function_definitions.internal_function import generate_ir_for_internal_function
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen.memory_allocator import MemoryAllocator
from vyper.utils import MemoryPositions, calc_mem_gas


# Is a function the initializer?
def is_initializer(code: vy_ast.FunctionDef) -> bool:
    return code.name == "__init__"


# Is a function the default function?
def is_default_func(code: vy_ast.FunctionDef) -> bool:
    return code.name == "__default__"


def generate_ir_for_function(
    code: vy_ast.FunctionDef,
    sigs: Dict[str, Dict[str, FunctionSignature]],
    global_ctx: GlobalContext,
    check_nonpayable: bool,
) -> Tuple[IRnode, int, int]:
    """
    Parse a function and produce IR code for the function, includes:
        - Signature method if statement
        - Argument handling
        - Clamping and copying of arguments
        - Function body
    """
    sig = FunctionSignature.from_definition(
        code,
        sigs=sigs,
        custom_structs=global_ctx._structs,
    )

    # Validate return statements.
    check_single_exit(code)

    # in order to statically allocate function frames,
    # we codegen functions in two passes.
    # one pass is just called for its side effects on the context/memory
    # allocator. once that pass is finished, we inspect the context
    # to see what the max frame size of any callee in the function was,
    # then we run the codegen again with the max frame size as
    # the start of the frame for this function.
    def _run_pass(memory_allocator=None):
        # Create a local (per function) context.
        if memory_allocator is None:
            memory_allocator = MemoryAllocator()
        nonlocal sig
        sig = copy.deepcopy(sig)  # just in case
        context = Context(
            vars_=None,
            global_ctx=global_ctx,
            sigs=sigs,
            memory_allocator=memory_allocator,
            return_type=sig.return_type,
            constancy=Constancy.Constant
            if sig.mutability in ("view", "pure")
            else Constancy.Mutable,
            is_payable=sig.mutability == "payable",
            is_internal=sig.internal,
            sig=sig,
        )

        if sig.internal:
            o = generate_ir_for_internal_function(code, sig, context)
        else:
            o = generate_ir_for_external_function(code, sig, context, check_nonpayable)

        o.source_pos = getpos(code)

        return o, context

    _, context = _run_pass(memory_allocator=None)

    allocate_start = context.max_callee_frame_size
    allocate_start += MemoryPositions.RESERVED_MEMORY

    o, context = _run_pass(memory_allocator=MemoryAllocator(allocate_start))

    frame_size = context.memory_allocator.size_of_mem - MemoryPositions.RESERVED_MEMORY

    if not sig.internal:
        # frame_size of external function includes all private functions called
        o.total_gas = o.gas + calc_mem_gas(frame_size)
    else:
        # frame size for internal function does not need to be adjusted
        # since it is already accounted for by the caller
        o.total_gas = o.gas

    o.context = context
    o.func_name = sig.name
    return o, allocate_start, frame_size
