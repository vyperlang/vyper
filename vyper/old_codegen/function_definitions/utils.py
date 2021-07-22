from vyper.old_codegen.lll_node import LLLnode


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


def make_unpacker(ident, i_placeholder, begin_pos):
    start_label = "dyn_unpack_start_" + ident
    end_label = "dyn_unpack_end_" + ident
    return [
        "seq_unchecked",
        ["mstore", begin_pos, "pass"],  # get len
        ["mstore", i_placeholder, 0],
        ["label", start_label],
        [  # break
            "if",
            ["ge", ["mload", i_placeholder], ["ceil32", ["mload", begin_pos]]],
            ["goto", end_label],
        ],
        [  # pop into correct memory slot.
            "mstore",
            ["add", ["add", begin_pos, 32], ["mload", i_placeholder]],
            "pass",
        ],
        ["mstore", i_placeholder, ["add", 32, ["mload", i_placeholder]]],  # increment i
        ["goto", start_label],
        ["label", end_label],
    ]


def get_nonreentrant_lock(func_type):
    nonreentrant_pre = [["pass"]]
    nonreentrant_post = [["pass"]]
    if func_type.nonreentrant:
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
