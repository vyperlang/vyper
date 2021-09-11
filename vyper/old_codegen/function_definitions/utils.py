def get_nonreentrant_lock(func_type):
    if not func_type.nonreentrant:
        return ["pass"], ["pass"]

    nkey = func_type.reentrancy_key_position.position
    nonreentrant_pre = [["seq", ["assert", ["iszero", ["sload", nkey]]], ["sstore", nkey, 1]]]
    nonreentrant_post = [["sstore", nkey, 0]]
    return nonreentrant_pre, nonreentrant_post
