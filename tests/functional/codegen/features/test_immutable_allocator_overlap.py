"""
Regression test for issue #4800: overlapping reserved memory intervals in Venom
could corrupt dynamic-string hashing during constructor execution.
"""


def test_immutable_hashing_overlap_regression(get_contract, make_input_bundle, keccak):
    module = """
NAME_HASH: immutable(bytes32)
VERSION_HASH: immutable(bytes32)
DOMAIN_SEPARATOR: immutable(bytes32)
PADDING: immutable(uint256[12])

EIP712_TYPEHASH: constant(bytes32) = keccak256(
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)

@deploy
def __init__(name_eip712_: String[50], version_eip712_: String[20]):
    VERSION_HASH = keccak256(version_eip712_)
    NAME_HASH = keccak256(name_eip712_)
    DOMAIN_SEPARATOR = keccak256(
        abi_encode(
            EIP712_TYPEHASH,
            NAME_HASH,
            VERSION_HASH,
            chain.id,
            self,
        )
    )
    PADDING = empty(uint256[12])
    """
    main = """
import eip712

initializes: eip712

@deploy
def __init__(name_eip712_: String[50], version_eip712_: String[20]):
    eip712.__init__(name_eip712_, version_eip712_)

@external
def get_name_hash() -> bytes32:
    return eip712.NAME_HASH

@external
def get_version_hash() -> bytes32:
    return eip712.VERSION_HASH
    """
    input_bundle = make_input_bundle({"eip712.vy": module})
    name = "N" * 50
    version = "V" * 20
    c = get_contract(main, name, version, input_bundle=input_bundle)
    assert c.get_name_hash() == keccak(name.encode())
    assert c.get_version_hash() == keccak(version.encode())
