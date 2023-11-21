# test syntactic comparisons
# most tests under tests/ast/nodes/test_evaluate_compare.py
import pytest


def test_3034_verbatim(get_contract):
    # test GH issue 3034 exactly
    code = """
@view
@external
def showError():
    adr1: address = 0xFbEEa1C75E4c4465CB2FCCc9c6d6afe984558E20
    adr2: address = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
    adr3: address = 0xFbEEa1C75E4c4465CB2FCCc9c6d6afe984558E20
    assert adr1 in [adr2,adr3], "error in comparison with in statement!"
    """
    c = get_contract(code)
    c.showError()


@pytest.mark.parametrize("invert", (True, False))
def test_in_list(get_contract, invert):
    # test slightly more complicated variations of #3034
    INVERT = "not" if invert else ""
    code = f"""
SOME_ADDRESS: constant(address) = 0x22cb70ba2EC32347D9e32740fc14b2f3d038Ce8E
@view
@external
def test_in(addr: address) -> bool:
    x: address = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
    y: address = 0xFbEEa1C75E4c4465CB2FCCc9c6d6afe984558E20
    # in list which
    return addr {INVERT} in [x, y, SOME_ADDRESS]
    """
    c = get_contract(code)
    should_in = [
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "0xFbEEa1C75E4c4465CB2FCCc9c6d6afe984558E20",
        "0x22cb70ba2EC32347D9e32740fc14b2f3d038Ce8E",
    ]
    should_not_in = [
        "0x" + "00" * 20,
        "0xfBeeA1C75E4C4465CB2fccC9C6d6AFe984558e21",  # y but last bit flipped
    ]
    for t in should_in:
        assert c.test_in(t) is (True if not invert else False)
    for t in should_not_in:
        assert c.test_in(t) is (True if invert else False)
