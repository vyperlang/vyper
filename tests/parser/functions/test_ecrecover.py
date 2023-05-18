from eth_account import Account
from eth_account._utils.signing import to_bytes32


def test_ecrecover_test(get_contract_with_gas_estimation):
    ecrecover_test = """
@external
def test_ecrecover(h: bytes32, v: uint8, r: bytes32, s: bytes32) -> address:
    return ecrecover(h, v, r, s)

@external
def test_ecrecover_uints(h: bytes32, v: uint256, r: uint256, s: uint256) -> address:
    return ecrecover(h, v, r, s)

@external
def test_ecrecover2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     28,
                     0x8bb954e648c468c01b6efba6cd4951929d16e5235077e2be43e81c0c139dbcdf,
                     0x0e8a97aa06cc123b77ccf6c85b123d299f3f477200945ef71a1e1084461cba8d)

@external
def test_ecrecover_uints2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     28,
                     63198938615202175987747926399054383453528475999185923188997970550032613358815,
                     6577251522710269046055727877571505144084475024240851440410274049870970796685)

    """

    c = get_contract_with_gas_estimation(ecrecover_test)

    h = b"\x35" * 32
    local_account = Account.from_key(b"\x46" * 32)
    sig = local_account.signHash(h)

    assert c.test_ecrecover(h, sig.v, to_bytes32(sig.r), to_bytes32(sig.s)) == local_account.address
    assert c.test_ecrecover_uints(h, sig.v, sig.r, sig.s) == local_account.address
    assert c.test_ecrecover2() == local_account.address
    assert c.test_ecrecover_uints2() == local_account.address

    print("Passed ecrecover test")
