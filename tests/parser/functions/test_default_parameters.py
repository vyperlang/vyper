

def test_default_param_abi(get_contract):
    code = """
@public
@payable
def safeTransferFrom(_data: bytes[100] = "test", _b: int128 = 1):
    pass
    """
    abi = get_contract(code)._classic_contract.abi

    assert len(abi) == 4
    assert set([fdef['name'] for fdef in abi]) == {'safeTransferFrom'}
    assert abi[0]['inputs'] == []
    assert abi[1]['inputs'] == [{'type': 'int128', 'name': '_b'}]
    assert abi[2]['inputs'] == [{'type': 'bytes', 'name': '_data'}]
    assert abi[3]['inputs'] == [{'type': 'bytes', 'name': '_data'}, {'type': 'int128', 'name': '_b'}]


def test_basic_default_param_passthrough(get_contract):
    code = """
@public
def fooBar(_data: bytes[100] = "test", _b: int128 = 1) -> int128:
    return 12321
    """

    c = get_contract(code)

    assert c.fooBar() == 12321
    assert c.fooBar(2) == 12321
    assert c.fooBar(b"drum drum") == 12321
    assert c.fooBar(b"drum drum", 2) == 12321


def test_basic_default_param_set(get_contract):
    code = """
@public
def fooBar(a:int128, b: uint256 = 333) -> (int128, uint256):
    return a, b
    """

    c = get_contract(code)
    assert c.fooBar(456, 444) == [456, 444]
