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


def test_simple_call_multiple_args_in_call(get_contract):
    code = """
@internal
def bar(_name: uint256, _name2: uint256) -> uint256:
    return _name + 10

@external
def foo(x: uint256) -> uint256:
    ret: uint256 = self.bar(20, 10)
    return ret
    """

    c = get_contract(code)
    assert c.foo(1) == 30


def test_simple_call_multiple_args(get_contract):
    code = """
@internal
def bar(_name: uint256, _name2: uint256) -> (uint256, uint256):
    return _name + 1, _name + 2

@external
def foo(x: uint256) -> (uint256, uint256):
    ret: (uint256, uint256) = self.bar(20, 10)
    return ret
    """

    c = get_contract(code)
    assert c.foo(1) == (21, 22)


def test_call_in_call(get_contract):
    code = """
@internal
def _foo(a: uint256) -> uint256:
    return a

@external
def foo() -> uint256:
    a: uint256 = 1
    return self._foo(a)
"""

    c = get_contract(code)

    assert c.foo() == 1


def test_2d_array_input_1(get_contract):
    code = """
@internal
def test_input(arr: DynArray[DynArray[int128, 2], 1]) -> DynArray[DynArray[int128, 2], 1]:
    return arr

@external
def test_values(arr: DynArray[DynArray[int128, 2], 1]) -> DynArray[DynArray[int128, 2], 1]:
    return self.test_input(arr)
    """

    c = get_contract(code)
    assert c.test_values([[1, 2]]) == ([[1, 2]])


def test_call_with_unused_params(get_contract):
    code = """
@internal
def _foo3(a: uint256, b: uint256) -> uint256:
    return 42

@external
def foo() -> uint256:
    return self._foo3(9, 11)
    """

    c = get_contract(code)

    assert c.foo() == 42


def test_internal_assign(get_contract):
    code = """
@internal
def foo(x: uint256) -> uint256:
    x = 10
    return x

@external
def bar(x: uint256) -> uint256:
    return self.foo(x)
    """
    c = get_contract(code)

    assert c.bar(70) == 10


def test_internal_assign(get_contract):
    code = """
@internal
def foo(x: uint256, y: int128) -> uint256:
    x = convert(y, uint256)
    return x

@external
def bar(x: uint256) -> uint256:
    return self.foo(x, 11)
    """
    c = get_contract(code)

    assert c.bar(70) == 11
