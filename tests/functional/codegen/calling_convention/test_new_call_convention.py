def test_call_unused_param_return_tuple(get_contract):
    code = """
@internal
def _foo(a: uint256, b: uint256) -> (uint256, uint256):
    return a, b

@external
def foo() -> (uint256, uint256):
    return self._foo(1, 2)
    """

    c = get_contract(code)

    assert c.foo() == (1, 2)


def test_returning_immutables(get_contract):
    """
    This test checks that we can return an immutable from an internal function, which results in
    the immutable being copied into the return buffer with `dloadbytes`.
    """
    contract = """
a: immutable(uint256)

@deploy
def __init__():
    a = 5

@internal
def get_my_immutable() -> uint256:
    return a

@external
def get_immutable() -> uint256:
    return self.get_my_immutable()
    """
    c = get_contract(contract)
    assert c.get_immutable() == 5
