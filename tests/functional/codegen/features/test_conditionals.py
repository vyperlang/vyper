def test_conditional_return_code(get_contract):
    conditional_return_code = """
@external
def foo(i: bool) -> int128:
    if i:
        return 5
    else:
        assert 2 != 0
        return 7
    """

    c = get_contract(conditional_return_code)
    assert c.foo(True) == 5
    assert c.foo(False) == 7

    print("Passed conditional return tests")


def test_single_branch_underflow_public(get_contract):
    code = """
@external
def doit():
    if False:
        raw_call(msg.sender, b"", max_outsize=0, value=0, gas=msg.gas)
    """
    c = get_contract(code)
    c.doit()


def test_single_branch_underflow_private(get_contract):
    code = """
@internal
def priv() -> uint256:
    return 1

@external
def dont_doit():
    if False:
        self.priv()
    """
    c = get_contract(code)
    c.dont_doit()


def test_nested_branch_inside_unreachable_branch(get_contract):
    # each outer condition can never hold (`qux`: disjoint ranges), so the
    # range analysis sees `x` as empty inside it. The nested comparisons
    # and the signextend from `unsafe_add` on int8 (`bar`) must still compile
    code = """
@external
def foo(a: uint256) -> uint256:
    x: uint256 = a & 255
    if x > 255:
        if x > 7:
            return 1
        return 2
    return 3

@external
def bar(a: uint256) -> int8:
    x: uint256 = a & 255
    if x > 255:
        y: int8 = convert(x, int8)
        return unsafe_add(y, y)
    return 3

@external
def baz(a: uint256) -> uint256:
    x: uint256 = a & 255
    if 255 < x:
        if 7 < x:
            return 1
        return 2
    return 3

@external
def qux(a: uint256, b: uint256) -> uint256:
    x: uint256 = a & 255
    y: uint256 = (b & 255) + 1000
    if x == y:
        if x > 7:
            return 1
        return 2
    return 3
    """
    c = get_contract(code)
    for a in (0, 7, 8, 255, 256, 2**256 - 1):
        assert c.foo(a) == 3
        assert c.bar(a) == 3
        assert c.baz(a) == 3
        assert c.qux(a, a) == 3
