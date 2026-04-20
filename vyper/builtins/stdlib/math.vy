@pure
@internal
def isqrt(x: uint256) -> uint256:
    """Integer square root using Babylonian method.
    Returns floor(sqrt(x)).
    """
    if x == 0:
        return 0

    y: uint256 = x
    z: uint256 = 181

    if y >= 2 ** 136:
        y = y >> 128
        z = z << 64
    if y >= 2 ** 72:
        y = y >> 64
        z = z << 32
    if y >= 2 ** 40:
        y = y >> 32
        z = z << 16
    if y >= 2 ** 24:
        y = y >> 16
        z = z << 8

    z = z * (y + 65536) // 4 ** 9

    for i: uint256 in range(7):
        z = (x // z + z) // 2

    t: uint256 = x // z
    return min(z, t)


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
