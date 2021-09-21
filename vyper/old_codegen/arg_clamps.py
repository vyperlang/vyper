from vyper.evm.opcodes import version_check

# TODO this whole module should be replaced with parser_utils.clamp_basetype


def _shr(x, bits):
    if version_check(begin="constantinople"):
        return ["shr", bits, x]
    return ["div", x, ["exp", 2, bits]]


def _sar(x, bits):
    if version_check(begin="constantinople"):
        return ["sar", bits, x]

    # emulate for older arches. keep in mind note from EIP 145:
    # This is not equivalent to PUSH1 2 EXP SDIV, since it rounds
    # differently. See SDIV(-1, 2) == 0, while SAR(-1, 1) == -1.
    return ["sdiv", ["add", ["slt", x, 0], x], ["exp", 2, bits]]


def address_clamp(lll_node):
    return ["assert", ["iszero", _shr(lll_node, 160)]]


def int128_clamp(lll_node):
    return [
        "with",
        "_val",
        lll_node,
        [
            "seq",
            # if _val is in bounds,
            # _val >>> 127 == 0 for positive _val
            # _val >>> 127 == -1 for negative _val
            # -1 and 0 are the only numbers which are unchanged by sar,
            # so sar'ing (_val>>>127) one more bit should leave it unchanged.
            ["assert", ["eq", _sar("_val", 128), _sar("_val", 127)]],
            "_val",
        ],
    ]
