from vyper.parser.context import Constancy, Context
from vyper.parser.function_definitions.parse_external_function import (  # NOTE black/isort conflict
    parse_external_function,
)
from vyper.parser.function_definitions.parse_internal_function import (  # NOTE black/isort conflict
    parse_internal_function,
)
from vyper.parser.memory_allocator import MemoryAllocator
from vyper.signatures import FunctionSignature
from vyper.utils import calc_mem_gas


# Is a function the initializer?
def is_initializer(code):
    return code.name == "__init__"


# Is a function the default function?
def is_default_func(code):
    return code.name == "__default__"


def parse_function(code, sigs, origcode, global_ctx, is_contract_payable, _vars=None):
    """
    Parses a function and produces LLL code for the function, includes:
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

    # Create a local (per function) context.
    memory_allocator = MemoryAllocator()
    context = Context(
        vars=_vars,
        global_ctx=global_ctx,
        sigs=sigs,
        memory_allocator=memory_allocator,
        return_type=sig.output_type,
        constancy=Constancy.Constant if sig.mutability in ("view", "pure") else Constancy.Mutable,
        is_payable=sig.mutability == "payable",
        origcode=origcode,
        is_internal=sig.internal,
        method_id=sig.method_id,
        sig=sig,
    )

    if sig.internal:
        o = parse_internal_function(code=code, sig=sig, context=context,)
    else:
        o = parse_external_function(
            code=code, sig=sig, context=context, is_contract_payable=is_contract_payable
        )

    o.context = context
    o.total_gas = o.gas + calc_mem_gas(o.context.memory_allocator.get_next_memory_position())
    o.func_name = sig.name
    return o
