import pytest


def test_import_interface_types(make_input_bundle, get_contract):
    ifaces = """
interface IFoo:
    def foo() -> uint256: nonpayable
    """

    foo_impl = """
import ifaces

implements: ifaces.IFoo

@external
def foo() -> uint256:
    return block.number
    """

    contract = """
import ifaces

@external
def test_foo(s: ifaces.IFoo) -> bool:
    assert extcall s.foo() == block.number
    return True
    """

    input_bundle = make_input_bundle({"ifaces.vy": ifaces})

    foo = get_contract(foo_impl, input_bundle=input_bundle)
    c = get_contract(contract, input_bundle=input_bundle)

    assert c.test_foo(foo.address) is True


def test_import_interface_types_stability(make_input_bundle, get_contract):
    lib1 = """
from ethereum.ercs import IERC20
    """
    lib2 = """
from ethereum.ercs import IERC20
    """

    main = """
import lib1
import lib2

from ethereum.ercs import IERC20

@external
def foo() -> bool:
    # check that this typechecks both directions
    a: lib1.IERC20 = IERC20(msg.sender)
    b: lib2.IERC20 = IERC20(msg.sender)
    c: IERC20 = lib1.IERC20(msg.sender)  # allowed in call position

    # return the equality so we can sanity check it
    return a == b and b == c
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() is True


@pytest.mark.parametrize("interface_syntax", ["__at__", "__interface__"])
def test_intrinsic_interface(get_contract, make_input_bundle, interface_syntax):
    lib = """
@external
@view
def foo() -> uint256:
    # detect self call
    if msg.sender == self:
        return 4
    else:
        return 5
    """

    main = f"""
import lib

exports: lib.__interface__

@external
@view
def bar() -> uint256:
    return staticcall lib.{interface_syntax}(self).foo()
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5
    assert c.bar() == 4


def test_import_interface_flags(make_input_bundle, get_contract):
    ifaces = """
flag Foo:
    BOO
    MOO
    POO

interface IFoo:
    def foo() -> Foo: nonpayable
    """

    contract = """
import ifaces

implements: ifaces

@external
def foo() -> ifaces.Foo:
    return ifaces.Foo.POO
    """

    input_bundle = make_input_bundle({"ifaces.vyi": ifaces})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.foo() == 4
