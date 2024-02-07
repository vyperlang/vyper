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

MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__(initial_value: uint256):
    self.counter = initial_value
    MY_IMMUTABLE = initial_value * 2

@internal
def increment_counter():
    self.counter += 1
    """

    contract = """
import library as lib

counter: public(uint256)

MY_IMMUTABLE: public(immutable(uint256))

initializes: lib

@deploy
def __init__():
    self.counter = 1
    MY_IMMUTABLE = 3
    lib.__init__(5)

@external
def get_lib_counter() -> uint256:
    return lib.counter

@external
def get_lib_immutable() -> uint256:
    return lib.MY_IMMUTABLE
    """

    input_bundle = make_input_bundle({"library.vy": lib})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.counter() == 1
    assert c.MY_IMMUTABLE() == 3
    assert c.get_lib_counter() == 5
    assert c.get_lib_immutable() == 10


def test_indirect_variable_uses(get_contract, make_input_bundle):
    lib1 = """
counter: uint256

MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__(initial_value: uint256):
    self.counter = initial_value
    MY_IMMUTABLE = initial_value * 2

@internal
def increment_counter():
    self.counter += 1
    """
    lib2 = """
import lib1

uses: lib1

@internal
def get_lib1_counter() -> uint256:
    return lib1.counter

@internal
def get_lib1_my_immutable() -> uint256:
    return lib1.MY_IMMUTABLE
    """

    contract = """
import lib1
import lib2

initializes: lib1
initializes: lib2[lib1 := lib1]

@deploy
def __init__():
    lib1.__init__(5)

@external
def get_storage_via_lib1() -> uint256:
    return lib1.counter

@external
def get_immutable_via_lib1() -> uint256:
    return lib1.MY_IMMUTABLE

@external
def get_storage_via_lib2() -> uint256:
    return lib2.get_lib1_counter()

@external
def get_immutable_via_lib2() -> uint256:
    return lib2.get_lib1_my_immutable()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.get_storage_via_lib1() == c.get_storage_via_lib2() == 5
    assert c.get_immutable_via_lib1() == c.get_immutable_via_lib2() == 10


def test_uses_already_initialized(get_contract, make_input_bundle):
    lib1 = """
counter: uint256
MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__(initial_value: uint256):
    self.counter = initial_value * 2
    MY_IMMUTABLE = initial_value * 3

@internal
def increment_counter():
    self.counter += 1
    """
    lib2 = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__(5)

@internal
def get_lib1_counter() -> uint256:
    return lib1.counter

@internal
def get_lib1_my_immutable() -> uint256:
    return lib1.MY_IMMUTABLE
    """

    contract = """
import lib1
import lib2

uses: lib1
initializes: lib2

@deploy
def __init__():
    lib2.__init__()

@external
def get_storage_via_lib1() -> uint256:
    return lib1.counter

@external
def get_immutable_via_lib1() -> uint256:
    return lib1.MY_IMMUTABLE

@external
def get_storage_via_lib2() -> uint256:
    return lib2.get_lib1_counter()

@external
def get_immutable_via_lib2() -> uint256:
    return lib2.get_lib1_my_immutable()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.get_storage_via_lib1() == c.get_storage_via_lib2() == 10
    assert c.get_immutable_via_lib1() == c.get_immutable_via_lib2() == 15


def test_import_complex_types(get_contract, make_input_bundle):
    lib1 = """
an_array: uint256[3]
a_hashmap: HashMap[address, HashMap[uint256, uint256]]

@internal
def set_array_value(ix: uint256, new_value: uint256):
    self.an_array[ix] = new_value

@internal
def set_hashmap_value(ix0: address, ix1: uint256, new_value: uint256):
    self.a_hashmap[ix0][ix1] = new_value
    """

    contract = """
import lib

initializes: lib

@external
def do_things():
    lib.set_array_value(1, 5)
    lib.set_hashmap_value(msg.sender, 6, 100)

@external
def get_array_value(ix: uint256) -> uint256:
    return lib.an_array[ix]

@external
def get_hashmap_value(ix: uint256) -> uint256:
    return lib.a_hashmap[msg.sender][ix]
    """

    input_bundle = make_input_bundle({"lib.vy": lib1})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.get_array_value(0) == 0
    assert c.get_hashmap_value(0) == 0
    c.do_things(transact={})

    assert c.get_array_value(0) == 0
    assert c.get_hashmap_value(0) == 0
    assert c.get_array_value(1) == 5
    assert c.get_hashmap_value(6) == 100
