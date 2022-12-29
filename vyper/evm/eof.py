
def verifyHeader(bytecode: bytes) -> bool:
    return bytecode[0] == 0xef and bytecode[1] == 0x0 and bytecode[2] == 0x01