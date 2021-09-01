from vyper.old_codegen.lll_node import LLLnode


# TODO dead code
def get_sig_statements(sig, pos):
    method_id_node = LLLnode.from_list(sig.method_id, pos=pos, annotation=f"{sig.sig}")

    if sig.internal:
        sig_compare = 0
        private_label = LLLnode.from_list(
            ["label", f"priv_{sig.method_id}"], pos=pos, annotation=f"{sig.sig}"
        )
    else:
        sig_compare = ["eq", "_func_sig", method_id_node]
        private_label = ["pass"]

    return sig_compare, private_label


def get_nonreentrant_lock(func_type):
    if not func_type.nonreentrant:
        return [], []

    nkey = func_type.reentrancy_key_position.position
    nonreentrant_pre = [["seq", ["assert", ["iszero", ["sload", nkey]]], ["sstore", nkey, 1]]]
    nonreentrant_post = [["sstore", nkey, 0]]
    return nonreentrant_pre, nonreentrant_post


def get_default_names_to_set(primary_sig, default_sig):
    """
    Get names for default parameters that require a default value to be assigned.
    """

    current_sig_arg_names = [x.name for x in default_sig.args]
    for arg in primary_sig.default_args:
        if arg.arg not in current_sig_arg_names:
            yield arg.arg
