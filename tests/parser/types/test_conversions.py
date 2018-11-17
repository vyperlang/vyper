from vyper.exceptions import (
    InvalidLiteralException
)


def test_to_int128_conversions(get_contract_with_gas_estimation):
    contract = """
@public
def from_uint256(foo: uint256) -> int128:
    return convert(foo, int128)

@public
def from_bytes32(foo: uint256) -> int128:
    return convert(foo, int128)

@public
def from_bytes(foo: bytes[16]) -> int128:
    return convert(foo, int128)
    """

    c = get_contract_with_gas_estimation(contract)
    assert c.from_uint256(0) == 0
    assert c.from_uint256(2**256 - 1) == -1
