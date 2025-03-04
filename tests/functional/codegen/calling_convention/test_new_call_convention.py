def test_call_unused_param_return_tuple(get_contract):
    code = """
@internal
def _foo(a: uint256) -> (uint256, uint256):
    return 1, 2

@external
def foo() -> (uint256, uint256):
    return self._foo(1)
    """

    c = get_contract(code)

    assert c.foo() == (1, 2)