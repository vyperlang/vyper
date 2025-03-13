
@internal
@pure
def sqrt(x: decimal) -> decimal:
    assert x >= 0.0
    z: decimal = 0.0

    if x == 0.0:
        z = 0.0
    else:
        z = x / 2.0 + 0.5
        y: decimal = x

        for i: uint256 in range(256):
            if z == y:
                break
            y = z
            z = (x / z + z) / 2.0

        if y < z:
            z = y

    return z