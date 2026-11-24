# test syntactic comparisons
# most tests under tests/ast/nodes/test_evaluate_compare.py
import pytest

from tests.utils import decimal_to_int
from vyper.exceptions import TypeMismatch


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


composite_compares = [
    ("uint256[3]", "a: uint256[3], b: uint256[3]", "a", "b"),
    ("DynArray[uint256, 4]", "a: DynArray[uint256, 4], b: DynArray[uint256, 4]", "a", "b"),
    ("S", "a: S, b: S", "a", "b"),
    ("(uint256, uint256)", "x: uint256, y: uint256", "(x, y)", "(y, x)"),
    ("uint256[2]", "", "self.arr", "self.arr"),
    ("uint256[2]", "a: uint256[2]", "a", "empty(uint256[2])"),
]


@pytest.mark.parametrize("op", ["==", "!="])
@pytest.mark.parametrize("typ,args,lhs,rhs", composite_compares)
def test_compare_complex_types_blocked(get_contract, op, typ, args, lhs, rhs):
    # GH issue 4960: venom used to compile these to a compare of the two memory
    # pointers. both pipelines must reject them until GH issue 2638 is done
    code = f"""
struct S:
    x: uint256
    y: uint256

arr: uint256[2]

@external
def foo({args}) -> bool:
    return {lhs} {op} {rhs}
    """
    with pytest.raises(TypeMismatch) as e:
        get_contract(code)
    assert e.value.message == f"operation not yet supported for {typ}, {typ}, see issue #2638"


def test_compare_word_types(get_contract):
    # word types that reach the composite type check in Compare still compile
    code = """
flag F:
    A
    B

interface I:
    def foo(): nonpayable

@external
def foo(f: F, i: I, b: bytes4, d: decimal, t: bool) -> bool:
    return f == F.A and i != I(self) and b == 0x01020304 and d == 1.5 and t == True
    """
    c = get_contract(code)
    assert c.foo(1, c.address, b"\x01\x02\x03\x04", decimal_to_int("1.5"), True) is False
    assert c.foo(1, "0x" + "00" * 20, b"\x01\x02\x03\x04", decimal_to_int("1.5"), True) is True
    assert c.foo(2, "0x" + "00" * 20, b"\x01\x02\x03\x04", decimal_to_int("1.5"), True) is False
    assert c.foo(1, "0x" + "00" * 20, b"\x01\x02\x03\x04", decimal_to_int("1.5"), False) is False
