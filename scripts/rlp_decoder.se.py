# Fetches the char from calldata at position $x
macro calldatachar($x):
    div(calldataload($x), 2**248)

# Fetches the next $b bytes from calldata starting at position $x 
# Assumes that there is nothing important in memory at bytes 0..63
macro calldatabytes_as_int($x, $b):
    ~mstore(32-$b, calldataload($x))
    ~mload(0)

with positions = 64:
    # Index of the next position we are adding to
    with positionIndex = 0:
        # Output data (main part)
        with data = 1088:
            # Index of where we are adding data
            with dataPos = 0:
                # Can only parse lists; check the length of the list and set the index
                # in calldata to the right start position

                # Get the first char of calldata
                with c = calldatachar(0):
                    # Position in the RLP object
                    with i = 0:
                        # Must be a list
                        assert c >= 192
                        # Case 1: short (length ++ data)
                        if c < 248:
                            assert ~calldatasize() == (c - 191)
                            i = 1
                        # Case 2: long (length of length ++ length ++ data)
                        else:
                            assert ~calldatasize() == (c - 246) + calldatabytes_as_int(i + 1, c - 247)
                            i = (c - 246)

                        # Main loop
                        # Here, we simultaneously build up data in two places:
                        # (i) starting from memory index 64, a list of 32-byte numbers
                        #     representing the start positions of each value
                        # (ii) starting from memory index 1088, the values, in format
                        #     <length as 32 byte int> <value>, packed one after the other
                        while i < ~calldatasize():
                            # Get type (single byte, short, long)
                            with c = calldatachar(i):
                                ~mstore(positions + positionIndex * 32, dataPos)
                                positionIndex += 1
                                # Single byte < 0x80
                                if c < 128:
                                    mstore(data + dataPos, 1)
                                    calldatacopy(data + 32 + dataPos, i, 1)
                                    i += 1
                                    dataPos += 33
                                # Short (up to 55 bytes)
                                elif c < 184:
                                    mstore(data + dataPos, c - 128)
                                    calldatacopy(data + 32 + dataPos, i + 1, c - 128)
                                    # Output could have been in single-byte format
                                    if c == 129:
                                        assert calldatachar(i + 1) >= 128
                                    i += c - 127
                                    dataPos += c - 96
                                # Long (56 or more bytes)
                                elif c < 192:
                                    with L = calldatabytes_as_int(i + 1, c - 183):
                                        # Forbid leading zero byte
                                        # Forbid too short values
                                        assert (calldatachar(i + 1) * (L >= 56))
                                        mstore(data + dataPos, L)
                                        calldatacopy(data + 32 + dataPos, i + c - 182, L)
                                        i += (c - 182) + L
                                        dataPos += L + 32
                                else:
                                    # Not handling nested arrays
                                    ~invalid()
                        # Max length 31 items
                        assert positionIndex <= 31
                        # Run a loop shifting the locations of the values representing the
                        # seek positions (ie. saved above in memory 0...1023) to the right
                        # place just before the output
                        with positionOffset = positionIndex * 32 + 32:
                            # Reuse i as a loop index, counting down by 32
                            i = positionOffset - 32
                            while i >= 0:
                                # Add to each value the total size of the portion of data that
                                # represents the seek positions
                                ~mstore(data - positionOffset + i, ~mload(positions + i) + positionOffset)
                                i -= 32
                            # The last value is the end of the returned data
                            ~mstore(data - 32, dataPos + positionOffset)
                            # Return the data from the right start position
                            ~return(data - positionOffset, positionOffset + dataPos)
