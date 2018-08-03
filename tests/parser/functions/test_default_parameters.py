

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
