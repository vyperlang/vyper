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
    # test what happens when things in current and imported modules share names
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


def test_init_function_side_effects(get_contract, make_input_bundle):
    lib = """
counter: uint256

@deploy
def __init__(initial_value: uint256):
    self.counter = initial_value

@internal
def increment_counter():
    self.counter += 1
    """

    contract = """
import library as lib

counter: public(uint256)

initializes: lib

@deploy
def __init__():
    self.counter = 1
    lib.__init__(5)

@external
def get_lib_counter() -> uint256:
    return lib.counter
    """

    input_bundle = make_input_bundle({"library.vy": lib})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.counter() == 1
    assert c.get_lib_counter() == 5


def test_variables_readable_no_uses(get_contract, make_input_bundle):
    # test we can read imported variables without using `uses`
    lib1 = """
counter: uint256

@deploy
def __init__(initial_value: uint256):
    self.counter = initial_value

@internal
def increment_counter():
    self.counter += 1
    """

    lib2 = """
import lib1

# no uses!

@internal
def get_lib1_counter():
    return lib1.counter
    """

    contract = """
import lib1
import lib2

initializes: lib1

@deploy
def __init__():
    lib1.__init__(5)

@external
def get_lib1_counter() -> uint256:
    return lib2.get_lib1_counter()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(contract, input_bundle=input_bundle)

    assert c.get_lib1_counter() == 5
