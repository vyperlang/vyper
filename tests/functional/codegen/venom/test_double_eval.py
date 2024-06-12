def test_double_eval_pop(get_contract):
    code = """
m: HashMap[uint256, String[33]]

@external
def foo() -> uint256:
    x: DynArray[uint256, 16] = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    self.m[x.pop()] = "Hello world"
    return len(x)
"""

    c = get_contract(code)
    assert c.foo() == 15
