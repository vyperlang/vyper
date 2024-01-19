
def test_simple_import(get_contract, make_input_bundle):
    lib1 = """
counter: uint256

@internal
def increment_counter():
    self.counter += 1
    """

    contract = """
import lib

initializes: lib

@external
def increment_counter():
    lib.increment_counter()

@external
def get_counter() -> uint256:
    return lib.counter
    """

    input_bundle = make_input_bundle({"lib.vy": lib1})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.get_counter() == 0
    c.increment_counter(transact={})
    assert c.get_counter() == 1
