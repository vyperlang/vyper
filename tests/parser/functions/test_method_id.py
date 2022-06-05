def test_method_id_test(get_contract_with_gas_estimation):
    method_id_test = """
@external
def double(x: int128) -> int128:
    return x * 2

@external
def returnten() -> int128:
    ans: Bytes[32] = raw_call(self, concat(method_id("double(int128)"), convert(5, bytes32)), gas=50000, max_outsize=32)  # noqa: E501
    return convert(convert(ans, bytes32), int128)
    """
    c = get_contract_with_gas_estimation(method_id_test)
    assert c.returnten() == 10


def test_method_id_bytes4(get_contract):
    code = """
@external
def sig() -> bytes4:
    return method_id('transfer(address,uint256)', output_type=bytes4)
    """
    c = get_contract(code)
    sig = c.sig()

    assert sig == b"\xa9\x05\x9c\xbb"


def test_method_id_Bytes4(get_contract):
    code = """
@external
def sig() -> Bytes[4]:
    return method_id('transfer(address,uint256)', output_type=Bytes[4])
    """
    c = get_contract(code)
    sig = c.sig()

    # assert len(sig) == 4
    assert sig == b"\xa9\x05\x9c\xbb"


def test_method_id_bytes4_default(get_contract):
    code = """
@external
def sig() -> Bytes[4]:
    return method_id('transfer(address,uint256)')
    """
    c = get_contract(code)
    sig = c.sig()

    # assert len(sig) == 4
    assert sig == b"\xa9\x05\x9c\xbb"


def test_method_id_invalid_space(get_contract, assert_compile_failed):
    code = """
@external
def sig() -> bytes4:
    return method_id('transfer(address, uint256)', output_type=bytes4)
    """
    assert_compile_failed(lambda: get_contract(code))


def test_method_id_invalid_type(get_contract, assert_compile_failed):
    code = """
@external
def sig() -> bytes32:
    return method_id('transfer(address,uint256)', output_type=bytes32)
    """
    assert_compile_failed(lambda: get_contract(code))
