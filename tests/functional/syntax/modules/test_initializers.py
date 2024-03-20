"""
tests for the uses/initializes checker
main properties to test:
- state usage -- if a module uses state, it must `used` or `initialized`
- conversely, if a module does not touch state, it should not be `used`
- global initializer check: each used module is `initialized` exactly once
"""

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import (
    BorrowException,
    ImmutableViolation,
    InitializerException,
    StructureException,
    UndeclaredDefinition,
)


def test_initialize_uses(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    pass
    """
    lib2 = """
import lib1

uses: lib1

counter: uint256

@deploy
def __init__():
    pass

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib2
import lib1

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_initialize_multiple_uses(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    pass
    """
    lib2 = """
totalSupply: uint256
    """
    lib3 = """
import lib1
import lib2

# multiple uses on one line
uses: (
    lib1,
    lib2
)

counter: uint256

@deploy
def __init__():
    pass

@internal
def foo():
    x: uint256 = lib2.totalSupply
    lib1.counter += 1
    """
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib2
initializes: lib3[
    lib1 := lib1,
    lib2 := lib2
]

@deploy
def __init__():
    lib1.__init__()
    lib3.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_initialize_multi_line_uses(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    pass
    """
    lib2 = """
totalSupply: uint256
    """
    lib3 = """
import lib1
import lib2

uses: lib1
uses: lib2

counter: uint256

@deploy
def __init__():
    pass

@internal
def foo():
    x: uint256 = lib2.totalSupply
    lib1.counter += 1
    """
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib2
initializes: lib3[
    lib1 := lib1,
    lib2 := lib2
]

@deploy
def __init__():
    lib1.__init__()
    lib3.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_initialize_uses_attribute(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    pass
    """
    lib2 = """
import lib1

uses: lib1

counter: uint256

@deploy
def __init__():
    pass

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib2.__init__()
    # demonstrate we can call lib1.__init__ through lib2.lib1
    # (not sure this should be allowed, really.
    lib2.lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_initializes_without_init_function(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

uses: lib1

counter: uint256

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    pass
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_imported_as_different_names(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1 as m

uses: m

counter: uint256

@internal
def foo():
    m.counter += 1
    """
    main = """
import lib1 as some_module
import lib2

initializes: lib2[m := some_module]
initializes: some_module
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_initializer_list_module_mismatch(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
something: uint256
    """
    lib3 = """
import lib1

uses: lib1

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib3[lib1 := lib2]  # typo -- should be [lib1 := lib1]
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})

    with pytest.raises(StructureException) as e:
        assert compile_code(main, input_bundle=input_bundle) is not None

    assert e.value._message == "lib1 is not lib2!"


def test_imported_as_different_names_error(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1 as m

uses: m

counter: uint256

@internal
def foo():
    m.counter += 1
    """
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(UndeclaredDefinition) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "unknown module `lib1`"
    assert e.value._hint == "did you mean `m := lib1`?"


def test_global_initializer_constraint(make_input_bundle, chdir_tmp_path):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

uses: lib1

counter: uint256

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
# forgot to initialize lib1!
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "module `lib1.vy` is used but never initialized!"
    assert e.value._hint == "add `initializes: lib1` to the top level of your main contract"


def test_initializer_no_references(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

uses: lib1

counter: uint256

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib1
import lib2

initializes: lib2
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "`lib2` uses `lib1`, but it is not initialized with `lib1`"
    assert e.value._hint == "add `lib1` to its initializer list"


def test_missing_uses(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!

counter: uint256

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib1
import lib2

initializes: lib2
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_read(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!

counter: uint256

@internal
def foo() -> uint256:
    return lib1.counter
    """
    main = """
import lib1
import lib2

initializes: lib1

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_read_immutable(make_input_bundle):
    lib1 = """
MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__():
    MY_IMMUTABLE = 7
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!

counter: uint256

@internal
def foo() -> uint256:
    return lib1.MY_IMMUTABLE
    """
    main = """
import lib1
import lib2

initializes: lib1

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_read_inside_call(make_input_bundle):
    lib1 = """
MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__():
    MY_IMMUTABLE = 9

@internal
def get_counter() -> uint256:
    return MY_IMMUTABLE
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!

counter: uint256

@internal
def foo() -> uint256:
    return lib1.get_counter()
    """
    main = """
import lib1
import lib2

initializes: lib1

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_hashmap(make_input_bundle):
    lib1 = """
counter: HashMap[uint256, HashMap[uint256, uint256]]
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!

@internal
def foo() -> uint256:
    return lib1.counter[1][2]
    """
    main = """
import lib1
import lib2

initializes: lib1

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_tuple(make_input_bundle):
    lib1 = """
counter: HashMap[uint256, HashMap[uint256, uint256]]
    """
    lib2 = """
import lib1

interface Foo:
    def foo() -> (uint256, uint256): nonpayable

something: uint256

# forgot `uses: lib1`!

@internal
def foo() -> uint256:
    lib1.counter[1][2], self.something = extcall Foo(msg.sender).foo()
    """
    main = """
import lib1
import lib2

initializes: lib1
initializes: lib2

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_tuple_function_call(make_input_bundle):
    lib1 = """
counter: HashMap[uint256, HashMap[uint256, uint256]]

something: uint256

interface Foo:
    def foo() -> (uint256, uint256): nonpayable

@internal
def write_tuple():
    self.counter[1][2], self.something = extcall Foo(msg.sender).foo()
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!
@internal
def foo():
    lib1.write_tuple()
    """
    main = """
import lib1
import lib2

initializes: lib1
initializes: lib2

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_function_call(make_input_bundle):
    # test missing uses through function call
    lib1 = """
counter: uint256

@internal
def update_counter(new_value: uint256):
    self.counter = new_value
    """
    lib2 = """
import lib1

# forgot `uses: lib1`!

counter: uint256

@internal
def foo():
    lib1.update_counter(lib1.counter + 1)
    """
    main = """
import lib1
import lib2

initializes: lib2
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_nested_attribute(make_input_bundle):
    # test missing uses through nested attribute access
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

counter: uint256

@internal
def foo():
    pass
    """
    main = """
import lib1
import lib2

initializes: lib1

# did not `use` or `initialize` lib2!

@external
def foo(new_value: uint256):
    # cannot access lib1 state through lib2
    lib2.lib1.counter = new_value
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib2` state!"

    expected_hint = "add `uses: lib2` or `initializes: lib2` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_subscript(make_input_bundle):
    # test missing uses through nested subscript/attribute access
    lib1 = """
struct Foo:
    array: uint256[5]

foos: Foo[5]
    """
    lib2 = """
import lib1

counter: uint256

@internal
def foo():
    pass
    """
    main = """
import lib1
import lib2

initializes: lib1

# did not `use` or `initialize` lib2!

@external
def foo(new_value: uint256):
    # cannot access lib1 state through lib2
    lib2.lib1.foos[0].array[1] = new_value
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib2` state!"

    expected_hint = "add `uses: lib2` or `initializes: lib2` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_nested_attribute_function_call(make_input_bundle):
    # test missing uses through nested attribute access
    lib1 = """
counter: uint256

@internal
def update_counter(new_value: uint256):
    self.counter = new_value
    """
    lib2 = """
import lib1

counter: uint256

@internal
def foo():
    pass
    """
    main = """
import lib1
import lib2

initializes: lib1

# did not `use` or `initialize` lib2!

@external
def foo(new_value: uint256):
    # cannot access lib1 state through lib2
    lib2.lib1.update_counter(new_value)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib2` state!"

    expected_hint = "add `uses: lib2` or `initializes: lib2` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_uses_skip_import(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

@internal
def foo():
    pass
    """
    main = """
import lib1
import lib2

initializes: lib2

@external
def foo(new_value: uint256):
    # cannot access lib1 state through lib2, lib2 does not `use` lib1.
    lib2.lib1.counter = new_value
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_uses_skip_import2(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

initializes: lib1

@internal
def foo():
    pass
    """
    main = """
import lib1
import lib2

initializes: lib2

@external
def foo(new_value: uint256):
    # *can* access lib1 state through lib2, because lib2 initializes lib1
    lib2.lib1.counter = new_value
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_invalid_uses(make_input_bundle, chdir_tmp_path):
    lib1 = """
counter: uint256
    """
    lib2 = """
import lib1

uses: lib1  # not necessary!

counter: uint256

@internal
def foo():
    pass
    """
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(BorrowException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "`lib1` is declared as used, but it is not actually used in lib2.vy!"
    assert e.value._hint == "delete `uses: lib1`"


def test_invalid_uses2(make_input_bundle, chdir_tmp_path):
    # test a more complicated invalid uses
    lib1 = """
counter: uint256

@internal
def foo(addr: address):
    # sends value -- modifies ethereum state
    to_send_value: uint256 = 100
    raw_call(addr, b"someFunction()", value=to_send_value)
    """
    lib2 = """
import lib1

uses: lib1  # not necessary!

counter: uint256

@internal
def foo():
    lib1.foo(msg.sender)
    """
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@external
def foo():
    lib2.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(BorrowException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "`lib1` is declared as used, but it is not actually used in lib2.vy!"
    assert e.value._hint == "delete `uses: lib1`"


def test_initializes_uses_conflict(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1

initializes: lib1
uses: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "ownership already set to `initializes`"


def test_uses_initializes_conflict(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1

uses: lib1
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "ownership already set to `uses`"


def test_uses_twice(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1

uses: lib1

random_variable: constant(uint256) = 3

uses: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "ownership already set to `uses`"


def test_initializes_twice(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1

initializes: lib1

random_variable: constant(uint256) = 3

initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "ownership already set to `initializes`"


def test_no_initialize_unused_module(make_input_bundle):
    lib1 = """
counter: uint256

@internal
def set_counter(new_value: uint256):
    self.counter = new_value

@internal
@pure
def add(x: uint256, y: uint256) -> uint256:
    return x + y
    """
    main = """
import lib1

# not needed: `initializes: lib1`

@external
def do_add(x: uint256, y: uint256) -> uint256:
    return lib1.add(x, y)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_no_initialize_unused_module2(make_input_bundle):
    # slightly more complicated
    lib1 = """
counter: uint256

@internal
def set_counter(new_value: uint256):
    self.counter = new_value

@internal
@pure
def add(x: uint256, y: uint256) -> uint256:
    return x + y
    """
    lib2 = """
import lib1

@internal
@pure
def addmul(x: uint256, y: uint256, z: uint256) -> uint256:
    return lib1.add(x, y) * z
    """
    main = """
import lib1
import lib2

@external
def do_addmul(x: uint256, y: uint256) -> uint256:
    return lib2.addmul(x, y, 5)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_uninitialized_function(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    pass
    """
    main = """
import lib1

# missing `initializes: lib1`!

@deploy
def __init__():
    lib1.__init__()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "tried to initialize `lib1`, but it is not in initializer list!"
    assert e.value._hint == "add `initializes: lib1` as a top-level statement to your contract"


def test_init_uninitialized_function2(make_input_bundle):
    # test that we can't call module.__init__() even when we call `uses`
    lib1 = """
counter: uint256

@deploy
def __init__():
    pass
    """
    main = """
import lib1

uses: lib1
# missing `initializes: lib1`!

@deploy
def __init__():
    lib1.__init__()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "tried to initialize `lib1`, but it is not in initializer list!"
    assert e.value._hint == "add `initializes: lib1` as a top-level statement to your contract"


def test_noinit_initialized_function(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    self.counter = 5
    """
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    pass  # missing `lib1.__init__()`!
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"
    assert e.value._hint == "add `lib1.__init__()` to your `__init__()` function"


def test_noinit_initialized_function2(make_input_bundle):
    lib1 = """
counter: uint256

@deploy
def __init__():
    self.counter = 5
    """
    main = """
import lib1

initializes: lib1

# missing `lib1.__init__()`!
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"
    assert e.value._hint == "add `lib1.__init__()` to your `__init__()` function"


def test_ownership_decl_errors_not_swallowed(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1
# forgot to import lib2

uses: (lib1, lib2)  # should get UndeclaredDefinition
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(UndeclaredDefinition) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "'lib2' has not been declared."


def test_partial_compilation(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1

uses: lib1

@internal
def use_lib1():
    lib1.counter += 1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    assert (
        compile_code(main, input_bundle=input_bundle, output_formats=["annotated_ast_dict"])
        is not None
    )
