import copy

from vyper.parser.global_context import (
    GlobalContext,
)
from vyper.signatures.event_signature import (
    EventSignature,
)
from vyper.signatures.function_signature import (
    FunctionSignature,
)


# Generate default argument function signatures.
def generate_default_arg_sigs(code, contracts, global_ctx):
    # generate all sigs, and attach.
    total_default_args = len(code.args.defaults)
    if total_default_args == 0:
        return [
            FunctionSignature.from_definition(
                code,
                sigs=contracts,
                custom_units=global_ctx._custom_units,
                custom_structs=global_ctx._structs,
                constants=global_ctx._constants
            )
        ]
    base_args = code.args.args[:-total_default_args]
    default_args = code.args.args[-total_default_args:]

    # Generate a list of default function combinations.
    row = [False] * (total_default_args)
    table = [row.copy()]
    for i in range(total_default_args):
        row[i] = True
        table.append(row.copy())

    default_sig_strs = []
    sig_fun_defs = []
    for truth_row in table:
        new_code = copy.deepcopy(code)
        new_code.args.args = copy.deepcopy(base_args)
        new_code.args.default = []
        # Add necessary default args.
        for idx, val in enumerate(truth_row):
            if val is True:
                new_code.args.args.append(default_args[idx])
        sig = FunctionSignature.from_definition(
            new_code,
            sigs=contracts,
            custom_units=global_ctx._custom_units,
            custom_structs=global_ctx._structs,
            constants=global_ctx._constants
        )
        default_sig_strs.append(sig.sig)
        sig_fun_defs.append(sig)

    return sig_fun_defs


def _default_sig_formatter(sig, custom_units_descriptions):
    return sig.to_abi_dict(custom_units_descriptions)


# Get ABI signature
def mk_full_signature(code, sig_formatter=None, interface_codes=None):

    if sig_formatter is None:
        # Use default JSON style output.
        sig_formatter = _default_sig_formatter

    o = []
    global_ctx = GlobalContext.get_global_context(code, interface_codes=interface_codes)

    # Produce event signatues.
    for code in global_ctx._events:
        sig = EventSignature.from_declaration(code, global_ctx)
        o.append(sig_formatter(sig, global_ctx._custom_units_descriptions))

    # Produce function signatures.
    for code in global_ctx._defs:
        sig = FunctionSignature.from_definition(
            code,
            sigs=global_ctx._contracts,
            custom_units=global_ctx._custom_units,
            custom_structs=global_ctx._structs,
            constants=global_ctx._constants
        )
        if not sig.private:
            default_sigs = generate_default_arg_sigs(code, global_ctx._contracts, global_ctx)
            for s in default_sigs:
                o.append(sig_formatter(s, global_ctx._custom_units_descriptions))
    return o


def mk_method_identifiers(code, interface_codes=None):
    from vyper.parser.parser import parse_to_ast
    o = {}
    global_ctx = GlobalContext.get_global_context(
        parse_to_ast(code),
        interface_codes=interface_codes,
    )

    for code in global_ctx._defs:
        sig = FunctionSignature.from_definition(
            code,
            sigs=global_ctx._contracts,
            custom_units=global_ctx._custom_units,
            constants=global_ctx._constants,
        )
        if not sig.private:
            default_sigs = generate_default_arg_sigs(code, global_ctx._contracts, global_ctx)
            for s in default_sigs:
                o[s.sig] = hex(s.method_id)

    return o
