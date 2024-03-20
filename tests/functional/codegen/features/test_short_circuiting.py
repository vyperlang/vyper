import itertools

import pytest


def test_short_circuit_and_left_is_false(w3, get_contract):
    code = """

called_left: public(bool)
called_right: public(bool)

@internal
def left() -> bool:
    self.called_left = True
    return False

@internal
def right() -> bool:
    self.called_right = True
    return False

@external
def foo() -> bool:
    return self.left() and self.right()
"""
    c = get_contract(code)
    assert not c.foo()

    c.foo(transact={})
    assert c.called_left()
    assert not c.called_right()


def test_short_circuit_and_left_is_true(w3, get_contract):
    code = """

called_left: public(bool)
called_right: public(bool)

@internal
def left() -> bool:
    self.called_left = True
    return True

@internal
def right() -> bool:
    self.called_right = True
    return True

@external
def foo() -> bool:
    return self.left() and self.right()
"""
    c = get_contract(code)
    assert c.foo()

    c.foo(transact={})
    assert c.called_left()
    assert c.called_right()


def test_short_circuit_or_left_is_true(w3, get_contract):
    code = """

called_left: public(bool)
called_right: public(bool)

@internal
def left() -> bool:
    self.called_left = True
    return True

@internal
def right() -> bool:
    self.called_right = True
    return True

@external
def foo() -> bool:
    return self.left() or self.right()
"""
    c = get_contract(code)
    assert c.foo()

    c.foo(transact={})
    assert c.called_left()
    assert not c.called_right()


def test_short_circuit_or_left_is_false(w3, get_contract):
    code = """

called_left: public(bool)
called_right: public(bool)

@internal
def left() -> bool:
    self.called_left = True
    return False

@internal
def right() -> bool:
    self.called_right = True
    return False

@external
def foo() -> bool:
    return self.left() or self.right()
"""
    c = get_contract(code)
    assert not c.foo()

    c.foo(transact={})
    assert c.called_left()
    assert c.called_right()


@pytest.mark.parametrize("op", ["and", "or"])
@pytest.mark.parametrize("a, b", itertools.product([True, False], repeat=2))
def test_from_memory(w3, get_contract, a, b, op):
    code = f"""
@external
def foo(a: bool, b: bool) -> bool:
    c: bool = a
    d: bool = b
    return c {op} d
"""
    c = get_contract(code)
    assert c.foo(a, b) == eval(f"{a} {op} {b}")


@pytest.mark.parametrize("op", ["and", "or"])
@pytest.mark.parametrize("a, b", itertools.product([True, False], repeat=2))
def test_from_storage(w3, get_contract, a, b, op):
    code = f"""
c: bool
d: bool

@external
def foo(a: bool, b: bool) -> bool:
    self.c = a
    self.d = b
    return self.c {op} self.d
"""
    c = get_contract(code)
    assert c.foo(a, b) == eval(f"{a} {op} {b}")


@pytest.mark.parametrize("op", ["and", "or"])
@pytest.mark.parametrize("a, b", itertools.product([True, False], repeat=2))
def test_from_calldata(w3, get_contract, a, b, op):
    code = f"""
@external
def foo(a: bool, b: bool) -> bool:
    return a {op} b
"""
    c = get_contract(code)
    assert c.foo(a, b) == eval(f"{a} {op} {b}")


@pytest.mark.parametrize("a, b, c, d", itertools.product([True, False], repeat=4))
@pytest.mark.parametrize("ops", itertools.product(["and", "or"], repeat=3))
def test_complex_combination(w3, get_contract, a, b, c, d, ops):
    boolop = f"a {ops[0]} b {ops[1]} c {ops[2]} d"

    code = f"""
@external
def foo(a: bool, b: bool, c: bool, d: bool) -> bool:
    return {boolop}
"""
    contract = get_contract(code)
    if eval(boolop):
        assert contract.foo(a, b, c, d)
    else:
        assert not contract.foo(a, b, c, d)
