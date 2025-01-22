
def test_simple_call(get_contract):
    code = """
@internal
def name(_name: uint256) -> uint256:
    return _name + 1


@external
def foo(x: uint256) -> uint256:
    u: uint256 = 1 + x
    ret: uint256 = self.name(u + 10)
    return ret
    """

    c = get_contract(code)
    assert c.foo(1) == 13

# def test_call_in_call(get_contract):
#     code = """
# @internal
# def _foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256, uint256, uint256, uint256):
#     return 1, a, b, c, 5

# @internal
# def _foo2() -> uint256:
#     a: uint256[10] = [6,7,8,9,10,11,12,13,15,16]
#     return 4

# @external
# def foo() -> (uint256, uint256, uint256, uint256, uint256):
#     return self._foo(2, 3, self._foo2())
#     """

#     c = get_contract(code)

#     assert c.foo() == (1, 2, 3, 4, 5)

