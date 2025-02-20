"""
Test functionality of internal functions which may be inlined
"""
# note for refactor: this may be able to be merged with
# calling_convention/test_internal_call.py


def test_call_in_call(get_contract):
    code = """
@internal
def _foo(a: uint256,) -> uint256:
    return 1 + a

@internal
def _foo2() -> uint256:
    return 4

@external
def foo() -> uint256:
    return self._foo(self._foo2())
    """

    c = get_contract(code)
    assert c.foo() == 5


def test_call_in_call_with_raise(get_contract, tx_failed):
    code = """
@internal
def sum(a: uint256) -> uint256:
    if a > 1:
        return a + 1
    raise

@internal
def middle(a: uint256) -> uint256:
    return self.sum(a)

@external
def test(a: uint256) -> uint256:
    return self.middle(a)
    """

    c = get_contract(code)

    assert c.test(2) == 3

    with tx_failed():
        c.test(0)


def test_inliner_with_unused_param(get_contract):
    code = """
data: public(uint256)

@internal
def _foo(start: uint256, length: uint256):
    self.data = start

@external
def foo(x: uint256, y: uint256):
    self._foo(x, y)
"""

    c = get_contract(code)
    c.foo(1, 2)
