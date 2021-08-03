# can't use from [module] import [object] because it breaks mocks in testing
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
from vyper.utils import calc_mem_gas


# Is a function the initializer?
def is_initializer(code):
    return code.name == "__init__"


# Is a function the default function?
def is_default_func(code):
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
    sig.validate_return_statement_balance()

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
        _vars = _vars.copy() # these will get clobbered in produce_* functions
        sig = copy.deepcopy(sig) # just in case
        context = ctx.Context(
            vars=_vars,
            global_ctx=global_ctx,
            sigs=sigs,
            memory_allocator=memory_allocator,
            return_type=sig.output_type,
            constancy=Constancy.Constant if sig.mutability in ("view", "pure") else Constancy.Mutable,
            is_payable=sig.mutability == "payable",
            is_internal=sig.internal,
            method_id=sig.method_id,
            sig=sig,
        )

        if sig.internal:
            o = parse_internal_function(code=code, sig=sig, context=context,)
        else:
            o = parse_external_function(
                code=code, sig=sig, context=context, check_nonpayable=check_nonpayable
            )
        return o, context

    _, context = _run_pass(None)
    allocate_start = max(ctx.callee_frame_sizes)
    o, context = _run_pass(MemoryAllocator(allocate_start))

    frame_size = context.memory_allocator.size_of_mem

    o.context = context
    o.total_gas = o.gas + calc_mem_gas(frame_size)
    o.func_name = sig.name
    return o, frame_size
