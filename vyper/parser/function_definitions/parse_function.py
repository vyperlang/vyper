from vyper.parser.context import (
    Constancy,
    Context,
)
from vyper.parser.function_definitions.parse_private_function import (
    parse_private_function,
)
from vyper.parser.function_definitions.parse_public_function import (
    parse_public_function,
)
from vyper.parser.memory_allocator import (
    MemoryAllocator,
)
from vyper.signatures import (
    FunctionSignature,
)
from vyper.utils import (
    calc_mem_gas,
)


# Is a function the initializer?
def is_initializer(code):
    return code.name == '__init__'


# Is a function the default function?
def is_default_func(code):
    return code.name == '__default__'


def parse_function(code, sigs, origcode, global_ctx, _vars=None):
    """
    Parses a function and produces LLL code for the function, includes:
        - Signature method if statement
        - Argument handling
        - Clamping and copying of arguments
        - Function body
    """
    if _vars is None:
        _vars = {}
    sig = FunctionSignature.from_definition(
        code,
        sigs=sigs,
        custom_units=global_ctx._custom_units,
        custom_structs=global_ctx._structs,
        constants=global_ctx._constants
    )

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
        constancy=Constancy.Constant if sig.const else Constancy.Mutable,
        is_payable=sig.payable,
        origcode=origcode,
        is_private=sig.private,
        method_id=sig.method_id
    )

    if sig.private:
        o = parse_private_function(
            code=code,
            sig=sig,
            context=context,
        )
    else:
        o = parse_public_function(
            code=code,
            sig=sig,
            context=context,
        )

    o.context = context
    o.total_gas = o.gas + calc_mem_gas(
        o.context.memory_allocator.get_next_memory_position()
    )
    o.func_name = sig.name
    return o
