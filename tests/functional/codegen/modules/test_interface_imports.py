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
