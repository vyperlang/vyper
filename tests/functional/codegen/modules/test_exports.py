import pytest


def test_simple_export(make_input_bundle, get_contract):
    lib1 = """
@external
def foo() -> uint256:
    return 5
    """
    main = """
import lib1

exports: lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5


def test_export_with_state(make_input_bundle, get_contract):
    lib1 = """
counter: uint256

@external
def foo() -> uint256:
    return self.counter
    """
    main = """
import lib1

initializes: lib1
exports: lib1.foo

@deploy
def __init__():
    lib1.counter = 99
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 99


def test_variable_decl_exports(make_input_bundle, get_contract):
    lib1 = """
counter: public(uint256)
FOO: public(immutable(uint256))
BAR: public(constant(uint256)) = 3

@deploy
def __init__():
    self.counter = 1
    FOO = 2
    """
    main = """
import lib1

initializes: lib1
exports: (
    lib1.counter,
    lib1.FOO,
    lib1.BAR,
)

@deploy
def __init__():
    lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.counter() == 1
    assert c.FOO() == 2
    assert c.BAR() == 3


def test_not_exported(make_input_bundle, get_contract):
    # test that non-exported functions are not in the selector table
    lib1 = """
@external
def foo() -> uint256:
    return 100

@external
def bar() -> uint256:
    return 101
    """
    main = """
import lib1

exports: lib1.foo

@external
def __default__() -> uint256:
    return 127
    """
    caller_code = """
interface Foo:
    def foo() -> uint256: nonpayable
    def bar() -> uint256: nonpayable

@external
def call_bar(foo: Foo) -> uint256:
    return extcall foo.bar()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    caller = get_contract(caller_code)

    assert caller.call_bar(c.address) == 127  # default return value


def test_nested_export(make_input_bundle, get_contract):
    lib1 = """
@external
def foo() -> uint256:
    return 5
    """
    lib2 = """
import lib1
    """
    main = """
import lib2

exports: lib2.lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5


# not sure if this one should work
@pytest.mark.xfail(reason="ambiguous spec")
def test_recursive_export(make_input_bundle, get_contract):
    lib1 = """
@external
def foo() -> uint256:
    return 5
    """
    lib2 = """
import lib1
exports: lib1.foo
    """
    main = """
import lib2

exports: lib2.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5
