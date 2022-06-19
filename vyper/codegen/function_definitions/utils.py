from vyper.semantics.types.function import StateMutability


def get_nonreentrant_lock(func_type):
    if not func_type.nonreentrant:
        return ["pass"], ["pass"]

    nkey = func_type.reentrancy_key_position.position

    if func_type.mutability == StateMutability.VIEW:
        return [["assert", ["iszero", ["sload", nkey]]]], [["seq"]]

    else:
        nonreentrant_pre = [["seq", ["assert", ["iszero", ["sload", nkey]]], ["sstore", nkey, 1]]]
        nonreentrant_post = [["sstore", nkey, 0]]
        return nonreentrant_pre, nonreentrant_post
