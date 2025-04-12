@pure
@internal
def sqrt(x: decimal) -> decimal:
    assert x >= 0.0

    if x == 0.0:
        return 0.0

    y: decimal = x
    z: decimal = x / 2.0 + 0.5

    for i: uint256 in range(256):
        if z == y:
            return z
        y = z
        z = (x / z + z) / 2.0

    # y and z can differ by 1 epsilon here. return the smaller
    # of the two for round-down behavior.
    return min(y, z)
