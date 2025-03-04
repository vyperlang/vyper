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