from vyper.evm.opcodes import version_check
from vyper.semantics.types.function import StateMutability


def get_nonreentrant_lock(func_type):
    if not func_type.nonreentrant:
        return ["pass"], ["pass"]

    nkey = func_type.reentrancy_key_position.position

    LOAD, STORE = "sload", "sstore"
    if version_check(begin="cancun"):
        LOAD, STORE = "tload", "tstore"

    if version_check(begin="berlin"):
        # any nonzero values would work here (see pricing as of net gas
        # metering); these values are chosen so that downgrading to the
        # 0,1 scheme (if it is somehow necessary) is safe.
        final_value, temp_value = 3, 2
    else:
        final_value, temp_value = 0, 1

    check_notset = ["assert", ["ne", temp_value, [LOAD, nkey]]]

    if func_type.mutability == StateMutability.VIEW:
        return [check_notset], [["seq"]]

    else:
        pre = ["seq", check_notset, [STORE, nkey, temp_value]]
        post = [STORE, nkey, final_value]
        return [pre], [post]
