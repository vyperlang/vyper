

def test_default_param_abi(get_contract):
    code = """
@public
@payable
def safeTransferFrom(_data: bytes[100] = "test", _b: int128 = 1):
    pass
    """
    abi = get_contract(code)._classic_contract.abi

    assert len(abi) == 3
    assert set([fdef['name'] for fdef in abi]) == {'safeTransferFrom'}
    assert abi[0]['inputs'] == []
    assert abi[1]['inputs'] == [{'type': 'bytes', 'name': '_data'}]
    assert abi[2]['inputs'] == [{'type': 'bytes', 'name': '_data'}, {'type': 'int128', 'name': '_b'}]


def test_basic_default_param_passthrough(get_contract):
    code = """
@public
def fooBar(_data: bytes[100] = "test", _b: int128 = 1) -> int128:
    return 12321
    """

    c = get_contract(code)

    assert c.fooBar() == 12321
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
    assert c.fooBar(456) == [456, 333]


def test_basic_default_param_set_2args(get_contract):
    code = """
@public
def fooBar(a:int128, b: uint256 = 999, c: address = 0x0000000000000000000000000000000000000001) -> (int128, uint256, address):
    return a, b, c
    """

    c = get_contract(code)
    c_default_value = '0x0000000000000000000000000000000000000001'
    b_default_value = 999
    addr2 = '0x1000000000000000000000000000000000004321'

    # b default value, c default value
    assert c.fooBar(123) == [123, b_default_value, c_default_value]
    # c default_value, b set from param
    assert c.fooBar(456, 444) == [456, 444, c_default_value]
    # no default values
    assert c.fooBar(6789, 4567, addr2) == [6789, 4567, addr2]


def test_default_param_bytes(get_contract):
    code = """
@public
def fooBar(a: bytes[100], b: int128, c: bytes[100] = "testing", d: uint256 = 999) -> (bytes[100], int128, bytes[100], uint256):
    return a, b, c, d
    """
    c = get_contract(code)
    c_default = b"testing"
    d_default = 999

    # c set, 7d default value
    assert c.fooBar(b"booo", 12321, b'woo') == [b"booo", 12321, b'woo', d_default]
    # d set, c set
    assert c.fooBar(b"booo", 12321, b"lucky", 777) == [b"booo", 12321, b"lucky", 777]
    # no default values
    assert c.fooBar(b"booo", 12321) == [b"booo", 12321, c_default, d_default]


def test_default_param_array(get_contract):
    code = """
@public
def fooBar(a: bytes[100], b: uint256[2], c: bytes[6] = "hello", d: int128[3] = [6, 7, 8]) -> (bytes[100], uint256, bytes[6], int128):
    return a, b[1], c, d[2]
    """
    c = get_contract(code)
    c_default = b"hello"
    d_default = 8

    # c set, d default value
    assert c.fooBar(b"booo", [99, 88], b'woo') == [b"booo", 88, b'woo', d_default]
    # d set, c set
    assert c.fooBar(b"booo", [22, 11], b"lucky", [24, 25, 26]) == [b"booo", 11, b"lucky", 26]
    # no default values
    assert c.fooBar(b"booo", [55, 66]) == [b"booo", 66, c_default, d_default]


def test_default_param_clamp(get_contract, monkeypatch, assert_tx_failed):
    code = """
@public
def bar(a: int128, b: int128 = -1) -> (int128, int128):
    return a, b
    """

    c = get_contract(code)

    assert c.bar(-123) == [-123, -1]
    assert c.bar(100, 100) == [100, 100]

    # bypass abi encoding checking:
    def utils_abi_is_encodable(_type, value):
        return True

    def validate_value(cls, value):
        pass

    monkeypatch.setattr('eth_abi.encoding.NumberEncoder.validate_value', validate_value)
    monkeypatch.setattr('web3.utils.abi.is_encodable', utils_abi_is_encodable)

    assert c.bar(200, 2**127 - 1) == [200, 2**127 - 1]
    assert_tx_failed(lambda: c.bar(200, 2**127))


def test_default_param_private(get_contract):
    code = """
@private
def fooBar(a: bytes[100], b: uint256, c: bytes[20] = "crazy") -> (bytes[100], uint256, bytes[20]):
    return a, b, c

@public
def callMe() -> (bytes[100], uint256, bytes[20]):
    return self.fooBar('I just met you', 123456)

@public
def callMeMaybe() -> (bytes[100], uint256, bytes[20]):
    # return self.fooBar('here is my number', 555123456, 'baby')
    a: bytes[100]
    b: uint256
    c: bytes[20]
    a, b, c = self.fooBar('here is my number', 555123456, 'baby')
    return a, b, c
    """

    c = get_contract(code)

    # assert c.callMe() == [b'hello there', 123456, b'crazy']
    assert c.callMeMaybe() == [b'here is my number', 555123456, b'baby']
