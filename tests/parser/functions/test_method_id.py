def test_method_id_test(get_contract_with_gas_estimation):
    method_id_test = """
@public
def double(x: int128) -> int128:
    return x * 2

@public
def returnten() -> int128:
    ans: bytes[32] = raw_call(self, concat(method_id("double(int128)", bytes[4]), convert(5, 'bytes32')), gas=50000, outsize=32)
    return convert(convert(ans, 'bytes32'), 'int128')
    """
    c = get_contract_with_gas_estimation(method_id_test)
    assert c.returnten() == 10
    print("Passed method ID test")


def test_method_id_bytes32(get_contract):
    code = """
@public
def sig() -> bytes32:
    return method_id('transfer(address,uint256)', bytes32)
    """
    c = get_contract(code)
    sig = c.sig()

    assert len(sig) == 32
    assert sig[-4:] == b"\xa9\x05\x9c\xbb"


def test_method_id_bytes4(get_contract):
    code = """
@public
def sig() -> bytes[4]:
    return method_id('transfer(address,uint256)', bytes[4])
    """
    c = get_contract(code)
    sig = c.sig()

    # assert len(sig) == 4
    assert sig == b"\xa9\x05\x9c\xbb"


def test_method_id_invalid_space(get_contract, assert_compile_failed):
    code = """
@public
def sig() -> bytes32:
    return method_id('transfer(address, uint256)', bytes32)
    """
    assert_compile_failed(lambda: get_contract(code))


def test_method_id_invalid_type(get_contract, assert_compile_failed):
    code = """
@public
def sig() -> int128:
    return method_id('transfer(address,uint256)', int128)
    """
    assert_compile_failed(lambda: get_contract(code))
