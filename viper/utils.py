# Converts for bytes to an integer
def fourbytes_to_int(inp):
    return (inp[0] << 24) + (inp[1] << 16) + (inp[2] << 8) + inp[3]

# Converts a provided hex string to an integer
def hex_to_int(inp):
    if inp[:2] == '0x':
        inp = inp[2:]
    return bytes_to_int(binascii.unhexlify(inp))

# Converts bytes to an integer
def bytes_to_int(bytez):
    o = 0
    for b in bytez:
        o = o * 256 + b
    return o
# A decimal value can store multiples of 1/DECIMAL_DIVISOR
DECIMAL_DIVISOR = 10000000000

# Number of bytes in memory used for system purposes, not for variables
RESERVED_MEMORY = 320
ADDRSIZE_POS = 32
MAXNUM_POS = 64
MINNUM_POS = 96
MAXDECIMAL_POS = 128
MINDECIMAL_POS = 160
FREE_VAR_SPACE = 192
BLANK_SPACE = 224
FREE_LOOP_INDEX = 256
