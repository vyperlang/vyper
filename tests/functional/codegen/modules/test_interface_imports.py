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

    # return the equality so we can sanity check it
    return a == b
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() is True
