macro calldatachar($x):
    div(calldataload($x), 2**248)

macro calldatabytes_as_int($x, $b):
    div(calldataload($x), 256**(32-$b))

def any():
    # Positions of the values that we are changing
    positions = array(256)
    # Index of the next position we are adding to
    positionIndex = 0
    # Output data (main part)
    data = string(~calldatasize() + 1024)
    # Index of where we are adding data
    dataPos = 0
    # Can only parse lists; check the length of the list and set the index
    # in calldata to the right start position
    c = calldatachar(0)
    if c < 192:
        ~invalid()
    if c < 248:
        if ~calldatasize() != 1 + (c - 192):
            ~invalid()
        i = 1
    else:
        L = calldatabytes_as_int(i + 1, c - 247)
        if ~calldatasize() != 1 + (c - 247) + L:
            ~invalid()
        i = 1 + (c - 247)
    # Main loop
    while i < ~calldatasize():
        # Get type (single byte, short, long)
        c = calldatachar(i)
        positions[positionIndex] = dataPos
        positionIndex += 1
        # Single byte < 0x80
        if c < 128:
            mstore(data + dataPos, 1)
            calldatacopy(data + dataPos + 32, i, 1)
            i += 1
            dataPos += 33
        # Short (up to 55 bytes)
        elif c < 184:
            mstore(data + dataPos, c - 128)
            calldatacopy(data + dataPos + 32, i + 1, c - 128)
            # Output could have been in single-byte format
            if c == 129:
                if calldatachar(i + 1) < 128:
                    ~invalid()
            i += c - 128 + 1
            dataPos += (c - 128) + 32
        # Long (56 or more bytes)
        elif c < 192:
            L = calldatabytes_as_int(i + 1, c - 183)
            # Forbid leading zero byte
            if calldatachar(i + 1) == 0:
                ~invalid()
            # Forbid too short values
            if L < 56:
                ~invalid()
            mstore(data + dataPos, L)
            calldatacopy(data + dataPos + 32, i + 1 + c - 183, L)
            i += (c - 183) + 1 + L
            dataPos += L + 32
        else:
            # Not handling nested arrays
            ~invalid()
        if positionIndex > 32:
            ~invalid()
    positions[positionIndex] = dataPos
    output = string(2048)
    i = 0
    while i <= positionIndex:
        output[i] = positions[i] + positionIndex * 32 + 32
        i += 1
    mcopy(output + positionIndex * 32 + 32, data, dataPos)
    ~return(output, positionIndex * 32 + dataPos + 32)
