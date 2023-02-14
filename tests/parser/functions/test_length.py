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


zero_length_cases = [
    """
@external
def boo() -> uint256:
    e: uint256 = len(empty(DynArray[uint256, 50]))
    return e
    """,
    """
@external
def boo() -> uint256:
    e: uint256 = len(empty(Bytes[50]))
    return e
    """,
    """
@external
def boo() -> uint256:
    e: uint256 = len(empty(String[50]))
    return e
    """,
]


@pytest.mark.parametrize("code", zero_length_cases)
def test_zero_length(get_contract_with_gas_estimation, code):
    c = get_contract_with_gas_estimation(code)
    assert c.boo() == 0
