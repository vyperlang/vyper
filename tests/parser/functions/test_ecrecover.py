from eth_account import Account


def test_ecrecover_test(get_contract_with_gas_estimation):
    ecrecover_test = """
@external
def test_ecrecover(h: bytes32, v:uint256, r:uint256, s:uint256) -> address:
    return ecrecover(h, v, r, s)

@external
def test_ecrecover2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     28,
                     63198938615202175987747926399054383453528475999185923188997970550032613358815,
                     6577251522710269046055727877571505144084475024240851440410274049870970796685)
    """

    c = get_contract_with_gas_estimation(ecrecover_test)

    h = b"\x35" * 32
    local_account = Account.privateKeyToAccount(b"\x46" * 32)
    sig = local_account.signHash(h)

    assert c.test_ecrecover(h, sig.v, sig.r, sig.s) == local_account.address
    assert c.test_ecrecover2() == local_account.address

    print("Passed ecrecover test")
