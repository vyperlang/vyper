def test_keccak_sanity(keccak):
    # sanity check -- ensure keccak is keccak256, not sha3
    # https://ethereum.stackexchange.com/a/107985
    assert keccak(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
