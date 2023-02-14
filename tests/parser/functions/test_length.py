import pytest


def test_test_length(get_contract_with_gas_estimation):
    test_length = """
y: Bytes[10]

@external
def foo(inp: Bytes[10]) -> uint256:
    x: Bytes[5] = slice(inp,1, 5)
    self.y = slice(inp, 2, 4)
    return len(inp) * 100 + len(x) * 10 + len(self.y)
    """

    c = get_contract_with_gas_estimation(test_length)
    assert c.foo(b"badminton") == 954, c.foo(b"badminton")
    print("Passed length test")


@pytest.mark.parametrize("typ", ["DynArray[uint256, 50]", "Bytes[50]", "String[50]"])
def test_zero_length(get_contract_with_gas_estimation, typ):
    code = f"""
@external
def boo() -> uint256:
    e: uint256 = len(empty({typ}))
    return e
    """

    c = get_contract_with_gas_estimation(code)
    assert c.boo() == 0
