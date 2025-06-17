def test_export_nonreentrant(make_input_bundle, get_contract, tx_failed):
    lib1 = """
interface Foo:
    def foo() -> uint256: nonpayable

implements: Foo

@external
@nonreentrant
def foo() -> uint256:
    return 5
    """
    main = """
import lib1

initializes: lib1

exports: lib1.foo

@external
@nonreentrant
def re_enter():
    extcall lib1.Foo(self).foo()  # should always throw

@external
def __default__():
    # sanity: make sure we don't revert due to bad selector
    pass
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 5
    with tx_failed():
        c.re_enter()


def test_internal_nonreentrant(make_input_bundle, get_contract, tx_failed):
    lib1 = """
interface Foo:
    def foo() -> uint256: nonpayable

implements: Foo

@external
def foo() -> uint256:
    return self._safe_fn()

@internal
@nonreentrant
def _safe_fn() -> uint256:
    return 10
    """
    main = """
import lib1

initializes: lib1

exports: lib1.foo

@external
@nonreentrant
def re_enter():
    extcall lib1.Foo(self).foo()  # should always throw

@external
def __default__():
    # sanity: make sure we don't revert due to bad selector
    pass
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 10
    with tx_failed():
        c.re_enter()
