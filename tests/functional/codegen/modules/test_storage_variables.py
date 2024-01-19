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


def test_import_namespace(get_contract, make_input_bundle):
    # test what happens when things in current and imported modules share
    # names
    lib = """
counter: uint256

@internal
def increment_counter():
    self.counter += 1
    """

    contract = """
import library as lib

counter: uint256

initializes: lib

@external
def increment_counter():
    self.counter += 1

@external
def increment_lib_counter():
    lib.increment_counter()

@external
def increment_lib_counter2():
    # modify lib.counter directly
    lib.counter += 5

@external
def get_counter() -> uint256:
    return self.counter

@external
def get_lib_counter() -> uint256:
    return lib.counter
    """

    input_bundle = make_input_bundle({"library.vy": lib})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.get_counter() == c.get_lib_counter() == 0

    c.increment_counter(transact={})
    assert c.get_counter() == 1
    assert c.get_lib_counter() == 0

    c.increment_lib_counter(transact={})
    assert c.get_lib_counter() == 1
    assert c.get_counter() == 1

    c.increment_lib_counter2(transact={})
    assert c.get_lib_counter() == 6
    assert c.get_counter() == 1
