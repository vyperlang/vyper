# can't use from [module] import [object] because it breaks mocks in testing
import copy

import vyper.ast as vy_ast
from vyper.ast.signatures import FunctionSignature
from vyper.old_codegen import context as ctx
from vyper.old_codegen.context import Constancy
from vyper.old_codegen.function_definitions.external_function import (
    generate_lll_for_external_function,
)
from vyper.old_codegen.function_definitions.internal_function import (
    generate_lll_for_internal_function,
)
from vyper.old_codegen.memory_allocator import MemoryAllocator
from vyper.old_codegen.parser_utils import check_single_exit
from vyper.utils import calc_mem_gas


# Is a function the initializer?
def is_initializer(code: vy_ast.FunctionDef):
    return code.name == "__init__"


# Is a function the default function?
def is_default_func(code: vy_ast.FunctionDef):
    return code.name == "__default__"


def generate_lll_for_function(code, sigs, global_ctx, check_nonpayable, _vars=None):
    """
    Parse a function and produce LLL code for the function, includes:
        - Signature method if statement
        - Argument handling
        - Clamping and copying of arguments
        - Function body
    """
    if _vars is None:
        _vars = {}
    sig = FunctionSignature.from_definition(code, sigs=sigs, custom_structs=global_ctx._structs,)

    # Validate return statements.
    check_single_exit(code)

    # in order to statically allocate function frames,
    # we codegen functions in two passes.
    # one pass is just called for its side effects on the context/memory
    # allocator. once that pass is finished, we inspect the context
    # to see what the max frame size of any callee in the function was,
    # then we run the codegen again with the max frame size as
    # the start of the frame for this function.
    def _run_pass(code, memory_allocator=None):
        # Create a local (per function) context.
        if memory_allocator is None:
            memory_allocator = MemoryAllocator()
        nonlocal _vars
        _vars = _vars.copy()  # these will get clobbered in called functions
        nonlocal sig
        sig = copy.deepcopy(sig)  # just in case
        context = ctx.Context(
            vars=_vars,
            global_ctx=global_ctx,
            sigs=sigs,
            memory_allocator=memory_allocator,
            return_type=sig.output_type,
            constancy=Constancy.Constant
            if sig.mutability in ("view", "pure")
            else Constancy.Mutable,
            is_payable=sig.mutability == "payable",
            is_internal=sig.internal,
            method_id=sig.method_id,
            sig=sig,
        )

        if sig.internal:
            o = generate_lll_for_internal_function(code, sig, context)
        else:
            o = generate_lll_for_external_function(code, sig, context, check_nonpayable)
        return o, context

    _, context = _run_pass(None)
    allocate_start = max(ctx.callee_frame_sizes)
    o, context = _run_pass(MemoryAllocator(allocate_start))

    frame_size = context.memory_allocator.size_of_mem

    if sig.external:
        # frame_size of external function includes all private functions called
        o.total_gas = o.gas + calc_mem_gas(frame_size)
    else:
        o.total_gas = o.gas

    o.context = context
    o.func_name = sig.name
    return o, allocate_start, frame_size
