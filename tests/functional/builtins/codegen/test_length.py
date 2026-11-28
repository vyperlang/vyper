import pytest


def test_test_length(get_contract):
    test_length = """
y: Bytes[10]

@external
def foo(inp: Bytes[10]) -> uint256:
    x: Bytes[5] = slice(inp,1, 5)
    self.y = slice(inp, 2, 4)
    return len(inp) * 100 + len(x) * 10 + len(self.y)
    """

    c = get_contract(test_length)
    assert c.foo(b"badminton") == 954, c.foo(b"badminton")
    print("Passed length test")


@pytest.mark.parametrize("typ", ["DynArray[uint256, 50]", "Bytes[50]", "String[50]"])
def test_zero_length(get_contract, typ):
    code = f"""
@external
def boo() -> uint256:
    e: uint256 = len(empty({typ}))
    return e
    """

    c = get_contract(code)
    assert c.boo() == 0


def test_len_list_literal(get_contract):
    # GH 3632
    code = """
X: constant(uint256) = len([1, 2, 3])

@external
def foo() -> uint256:
    return len([1, 2, 3])

@external
def bar() -> uint256:
    return X
    """

    c = get_contract(code)
    assert c.foo() == 3
    assert c.bar() == 3


def test_len_list_literal_side_effects(get_contract):
    code = """
counter: uint256

@internal
def bump() -> uint256:
    self.counter += 1
    return self.counter

@external
def foo(x: uint256) -> uint256:
    return len([x, self.bump(), self.bump()])

@external
def get_counter() -> uint256:
    return self.counter
    """

    c = get_contract(code)
    assert c.foo(5) == 3
    # the list elements must still be evaluated
    assert c.get_counter() == 2
