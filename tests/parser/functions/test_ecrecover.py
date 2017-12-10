def test_ecrecover_test(get_contract_with_gas_estimation, utils):
    ecrecover_test = """
@public
def test_ecrecover(h: bytes32, v:num256, r:num256, s:num256) -> address:
    return ecrecover(h, v, r, s)

@public
def test_ecrecover2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     as_num256(28),
                     as_num256(63198938615202175987747926399054383453528475999185923188997970550032613358815),
                     as_num256(6577251522710269046055727877571505144084475024240851440410274049870970796685))
    """

    c = get_contract_with_gas_estimation(ecrecover_test)
    h = b'\x35' * 32
    k = b'\x46' * 32
    v, r, S = utils.ecsign(h, k)
    assert c.test_ecrecover(h, v, r, S) == '0x' + utils.encode_hex(utils.privtoaddr(k))
    assert c.test_ecrecover2() == '0x' + utils.encode_hex(utils.privtoaddr(k))

    print("Passed ecrecover test")
