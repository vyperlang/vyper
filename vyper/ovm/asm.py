import string

import vyper.utils as util

# https://community.optimism.io/docs/protocol/protocol.html#execution-contracts
# * The CALLER, CALL, and REVERT opcodes are also disallowed, except in the special case that they appear as part of one of the following strings of bytecode:  # noqa: 501
# CALLER PUSH1 0x00 SWAP1 GAS CALL PC PUSH1 0x0E ADD JUMPI RETURNDATASIZE PUSH1 0x00 DUP1 RETURNDATACOPY RETURNDATASIZE PUSH1 0x00 REVERT JUMPDEST RETURNDATASIZE PUSH1 0x01 EQ ISZERO PC PUSH1 0x0a ADD JUMPI PUSH1 0x01 PUSH1 0x00 RETURN JUMPDEST  # noqa: 501
# CALLER POP PUSH1 0x00 PUSH1 0x04 GAS CALL

# Call into the OVM execution manager.
# this expects the last 4 args of CALL to already be on the stack:
# args_loc, args_len, return_loc, return_len
#
# CMC 2021-08-08 ovm_exec is basically
# success = call(gas, caller, 0, <4 stack args>)
# if (!success) {
#   -- fail with revert
#   returndatacopy(0, returndatasize);
#   revert(0, returndatasize);
# if (returndatasize()==1) {
#   return(0,1) -- according to optimism team this is a deprecated flow
# }


# quick/dirty util
def parse_asm_item(x):
    if x[:2] == "0x" and all(c in string.hexdigits for c in x[2:]):
        return util.hex_to_int(x)
    return x


ALLOWED_EXEC_STRING = "CALLER PUSH1 0x00 SWAP1 GAS CALL PC PUSH1 0x0E ADD JUMPI RETURNDATASIZE PUSH1 0x00 DUP1 RETURNDATACOPY RETURNDATASIZE PUSH1 0x00 REVERT JUMPDEST RETURNDATASIZE PUSH1 0x01 EQ ISZERO PC PUSH1 0x0a ADD JUMPI PUSH1 0x01 PUSH1 0x00 RETURN JUMPDEST"  # noqa: 501
OVM_EXEC_ASM = [parse_asm_item(x) for x in ALLOWED_EXEC_STRING.split(" ")]

# Call the identity precompile.
# this expects the last 4 args of identity precompile already on the stack:
# args_loc, args_len, return_loc, return_len
ALLOWED_COPY_STRING = "CALLER POP PUSH1 0x00 PUSH1 0x04 GAS CALL"
OVM_COPY_ASM = ALLOWED_COPY_STRING.split(" ")
OVM_COPY_ASM.append(
    "POP"
)  # always success unless OOG (YP) in which case it is too late to fail anyway.
OVM_COPY_ASM = [parse_asm_item(x) for x in OVM_COPY_ASM]


def rewrite_asm_for_ovm(asm):
    ret = []
    for x in asm:
        if isinstance(x, list):
            # this is a code block, append it whole
            ret.append(rewrite_asm_for_ovm(x))
        elif x == "OVM_COPY":
            ret.extend(OVM_COPY_ASM)
        elif x == "OVM_EXEC":
            ret.extend(OVM_EXEC_ASM)
        else:
            ret.append(x)
    return ret
