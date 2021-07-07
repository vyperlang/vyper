import copy

from vyper.ast.signatures.function_signature import FunctionSignature


# Generate default argument function signatures.
def generate_default_arg_sigs(code, interfaces, global_ctx):
    # generate all sigs, and attach.
    total_default_args = len(code.args.defaults)
    if total_default_args == 0:
        return [
            FunctionSignature.from_definition(
                code, sigs=interfaces, custom_structs=global_ctx._structs,
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
            new_code, sigs=interfaces, custom_structs=global_ctx._structs,
        )
        default_sig_strs.append(sig.sig)
        sig_fun_defs.append(sig)

    return sig_fun_defs


# Get ABI signature
def mk_full_signature(global_ctx, sig_formatter):
    o = []

    # Produce function signatures.
    for code in global_ctx._defs:
        sig = FunctionSignature.from_definition(
            code, sigs=global_ctx._contracts, custom_structs=global_ctx._structs,
        )
        if not sig.internal:
            default_sigs = generate_default_arg_sigs(code, global_ctx._contracts, global_ctx)
            for s in default_sigs:
                o.append(sig_formatter(s))
    return o
