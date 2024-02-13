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


def test_invalid_signature(get_contract):
    code = """
dummies: HashMap[address, HashMap[address, uint256]]

@external
def test_ecrecover(hash: bytes32, v: uint8, r: uint256) -> address:
    # read from hashmap to put garbage in 0 memory location
    s: uint256 = self.dummies[msg.sender][msg.sender]
    return ecrecover(hash, v, r, s)
    """
    c = get_contract(code)
    hash_ = bytes(i for i in range(32))
    v = 0  # invalid v! ecrecover precompile will not write to output buffer
    r = 0
    # note web3.py decoding of 0x000..00 address is None.
    assert c.test_ecrecover(hash_, v, r) is None


# slightly more subtle example: get_v() stomps memory location 0,
# so this tests that the output buffer stays clean during ecrecover()
# builtin execution.
def test_invalid_signature2(get_contract):
    code = """

owner: immutable(address)

@deploy
def __init__():
    owner = 0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf

@internal
def get_v() -> uint256:
    assert owner == owner # force a dload to write at index 0 of memory
    return 21

@payable
@external
def test_ecrecover() -> bool:
    assert ecrecover(empty(bytes32), self.get_v(), 0, 0) == empty(address)
    return True
    """
    c = get_contract(code)
    assert c.test_ecrecover() is True
