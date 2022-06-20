from vyper.evm.opcodes import version_check
from vyper.semantics.types.function import StateMutability


def get_nonreentrant_lock(func_type):
    if not func_type.nonreentrant:
        return ["pass"], ["pass"]

    nkey = func_type.reentrancy_key_position.position

    if version_check(begin="berlin"):
        final_value, temp_value = 1, 2
    else:
        final_value, temp_value = 0, 1

    check_notset = ["assert", ["ne", temp_value, ["sload", nkey]]]

    if func_type.mutability == StateMutability.VIEW:
        return [check_notset], [["seq"]]

    else:
        pre = ["seq", check_notset, ["sstore", nkey, temp_value]]
        post = ["sstore", nkey, final_value]
        return [pre], [post]
