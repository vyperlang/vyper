from hexbytes import HexBytes


def initcode(_addr):
    addr = HexBytes(_addr)
    pre = HexBytes("0x602D3D8160093D39F3363d3d373d3d3d363d73")
    post = HexBytes("0x5af43d82803e903d91602b57fd5bf3")
    return HexBytes(pre + (addr + HexBytes(0) * (20 - len(addr))) + post)


def test_create_forwarder_to_create(get_contract):
    code = """
main: address

@external
def test() -> address:
    self.main = create_forwarder_to(self)
    return self.main
    """

    c = get_contract(code)

    assert c.test() == "0x4F9DA333DCf4E5A53772791B95c161B2FC041859"


def test_create_forwarder_to_call(get_contract, w3):
    code = """

interface SubContract:

    def hello() -> Bytes[100]: view


other: public(address)


@external
def test() -> address:
    self.other = create_forwarder_to(self)
    return self.other


@external
def hello() -> Bytes[100]:
    return b"hello world!"


@external
def test2() -> Bytes[100]:
    return SubContract(self.other).hello()

    """

    c = get_contract(code)

    assert c.hello() == b"hello world!"
    c.test(transact={})
    assert c.test2() == b"hello world!"


def test_create_with_code_exception(w3, get_contract, assert_tx_failed):
    code = """

interface SubContract:

    def hello(a: uint256) -> Bytes[100]: view


other: public(address)


@external
def test() -> address:
    self.other = create_forwarder_to(self)
    return self.other


@external
def hello(a: uint256) -> Bytes[100]:
    assert a > 0, "invaliddddd"
    return b"hello world!"


@external
def test2(a: uint256) -> Bytes[100]:
    return SubContract(self.other).hello(a)
    """

    c = get_contract(code)

    assert c.hello(1) == b"hello world!"
    c.test(transact={})
    assert c.test2(1) == b"hello world!"

    assert_tx_failed(lambda: c.test2(0))

    GAS_SENT = 30000
    tx_hash = c.test2(0, transact={"gas": GAS_SENT})

    receipt = w3.eth.getTransactionReceipt(tx_hash)

    assert receipt["status"] == 0
    assert receipt["gasUsed"] < GAS_SENT


def test_create2_forwarder_to_create(get_contract, create2_address_of, keccak):
    code = """
main: address

@external
def test(_salt: bytes32) -> address:
    self.main = create_forwarder_to(self, salt=_salt)
    return self.main
    """

    c = get_contract(code)

    salt = keccak(b"vyper")
    assert HexBytes(c.test(salt)) == create2_address_of(c.address, salt, initcode(c.address))
