"""
tests for the uses/initializes checker
main properties to test:
- state usage -- if a module uses state, it must `used` or `initialized`
- conversely, if a module does not touch state, it should not be `used`
- global initializer check: each used module is `initialized` exactly once
"""

import pytest

from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.exceptions import (
    BorrowException,
    CallViolation,
    FunctionDeclarationException,
    ImmutableViolation,
    InitializerException,
    StructureException,
    UndeclaredDefinition,
)

from .helpers import NONREENTRANT_NOTE


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
    # demonstrate we can call lib1.__init__ through lib2.lib1
    # (not sure this should be allowed, really.
    lib2.lib1.__init__()
    lib2.__init__()
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


def test_valid_initialized_twice(make_input_bundle):
    # Initialized by both lib2 and lib3
    lib1 = """
counter: uint256
    """

    lib2 = """
import lib1

initializes: lib1
    """

    lib3 = """
import lib1

initializes: lib1
    """

    main = """
import lib2
import lib3

initializes: lib2
# lib3 not initialized, so lib1 is only initialized once
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})

    compile_code(main, input_bundle=input_bundle)


def test_invalid_initialized_twice(make_input_bundle):
    # Initialized by both lib2 and lib3
    lib1 = """
counter: uint256
    """

    lib2 = """
import lib1

initializes: lib1
    """

    lib3 = """
import lib1

initializes: lib1
    """

    main = """
import lib2
import lib3

# both initialize lib1, invalid!
initializes: lib2
initializes: lib3
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})

    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value.message == "`lib1` initialized twice!"


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
    assert e.value._hint == "did you mean lib2[lib1 := lib1]?"


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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_read_immutable(make_input_bundle):
    lib1 = """
MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__():
    self.MY_IMMUTABLE = 7
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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_missing_uses_for_read_inside_call(make_input_bundle):
    lib1 = """
MY_IMMUTABLE: immutable(uint256)

@deploy
def __init__():
    self.MY_IMMUTABLE = 9

@internal
def get_counter() -> uint256:
    return self.MY_IMMUTABLE
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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib2` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib2` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib2` state!" + NONREENTRANT_NOTE

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

    assert e.value._message == "Cannot access `lib1` state!" + NONREENTRANT_NOTE

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
    expected = "`lib1` is declared as used, but its state is not"
    expected += " actually used in lib2.vy!"
    assert e.value._message == expected
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
    expected = "`lib1` is declared as used, but its state is not "
    expected += "actually used in lib2.vy!"
    assert e.value._message == expected
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


def test_root_uses_forbidden(make_input_bundle):
    lib1 = """
counter: uint256
    """
    main = """
import lib1

uses: lib1

@external
def foo():
    lib1.counter += 1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "the top-level module cannot `uses:` another module"
    assert e.value._hint == "replace `uses: lib1` with `initializes: lib1`"


def test_root_uses_forbidden_tuple(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib2 = """
counter: uint256
    """
    main = """
import lib1
import lib2

uses: (lib1, lib2)

@external
def foo():
    lib1.counter += 1
    lib2.counter += 1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "the top-level module cannot `uses:` another module"
    assert e.value._hint == "replace `uses: lib1` with `initializes: lib1`"


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


def test_hint_for_missing_initializer_in_list(make_input_bundle):
    lib1 = """
counter: uint256
    """
    lib3 = """
counter: uint256
        """
    lib2 = """
import lib1
import lib3

uses: lib1
uses: lib3

counter: uint256

@internal
def foo():
    lib1.counter += 1
    lib3.counter += 1
    """
    main = """
import lib1
import lib2
import lib3

initializes: lib2[lib1:=lib1]
initializes: lib1
initializes: lib3
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "`lib2` uses `lib3`, but it is not initialized with `lib3`"
    assert e.value._hint == "add `lib3 := lib3` to its initializer list"


def test_hint_for_missing_initializer_when_no_import(make_input_bundle, chdir_tmp_path):
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
import lib2

initializes: lib2
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "`lib2` uses `lib1`, but it is not initialized with `lib1`"
    hint = "try importing `lib1` first (located at `lib1.vy`)"
    assert e.value._hint == hint


@pytest.fixture
def nonreentrant_library_bundle(make_input_bundle):
    # test simple case
    lib1 = """
# lib1.vy
@internal
@nonreentrant
def bar():
    pass

# lib1.vy
@external
@nonreentrant
def ext_bar():
    pass
    """
    # test case with recursion
    lib2 = """
@internal
def bar():
    self.baz()

@external
def ext_bar():
    self.baz()

@nonreentrant
@internal
def baz():
    return
    """
    # test case with nested recursion
    lib3 = """
import lib1
uses: lib1

@internal
def bar():
    lib1.bar()

@external
def ext_bar():
    lib1.bar()
    """

    return make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})


@pytest.mark.parametrize("lib", ("lib1", "lib2", "lib3"))
def test_nonreentrant_exports(nonreentrant_library_bundle, lib):
    main = f"""
import {lib}

exports: {lib}.ext_bar  # line 4

@external
def foo():
    pass
    """
    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=nonreentrant_library_bundle)
    assert e.value._message == f"Cannot access `{lib}` state!" + NONREENTRANT_NOTE
    hint = f"add `uses: {lib}` or `initializes: {lib}` as a top-level statement to your contract"
    assert e.value._hint == hint
    assert e.value.annotations[0].lineno == 4


@pytest.mark.parametrize("lib", ("lib1", "lib2", "lib3"))
def test_internal_nonreentrant_import(nonreentrant_library_bundle, lib):
    main = f"""
import {lib}

@external
def foo():
    {lib}.bar()  # line 6
    """
    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=nonreentrant_library_bundle)
    assert e.value._message == f"Cannot access `{lib}` state!" + NONREENTRANT_NOTE

    hint = f"add `uses: {lib}` or `initializes: {lib}` as a top-level statement to your contract"
    assert e.value._hint == hint
    assert e.value.annotations[0].lineno == 6


def test_global_initialize_missed_import_hint(make_input_bundle, chdir_tmp_path):
    lib1 = """
import lib2
import lib3

initializes: lib2[
    lib3 := lib3
]
    """
    lib2 = """
import lib3

uses: lib3

@external
def set_some_mod():
    a: uint256 = lib3.var
    """
    lib3 = """
var: uint256
    """
    main = """
import lib1

initializes: lib1
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "lib3.vy": lib3})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "module `lib3.vy` is used but never initialized!"
    assert e.value._hint is None


# import has nonreentrancy pragma on and an external function
# and thus must be initialized
def test_import_has_nonreentrancy_pragma(make_input_bundle, get_contract, tx_failed):
    lib1 = """
# pragma nonreentrancy on

@external
def bar():
    pass
    """
    main = """
import lib1

exports: lib1.bar
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message.startswith("Cannot access `lib1` state!")
    expected_hint = "add `uses: lib1` or `initializes: lib1` as a"
    expected_hint += " top-level statement to your contract"
    assert e.value._hint == expected_hint


# ===== Abstract/Override Initializer Tests =====
# Tests for uses/initializes requirements with @abstract/@override


def test_stateful_override_without_initializes(make_input_bundle):
    contract = """
import abstract_m
import override_m
import caller_m

initializes: caller_m[abstract_m := abstract_m]
# initializes: override_m # should fail gracefully without this

@external
def my_method() -> uint256:
    return caller_m.call_bar()
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    override_m = """
import abstract_m
initializes: abstract_m

counter: uint256

@override(abstract_m)
def bar() -> uint256:
    self.counter += 1
    return 101
    """

    caller_m = """
import abstract_m

uses: abstract_m

def call_bar() -> uint256:
    return abstract_m.bar()
    """
    input_bundle = make_input_bundle(
        {"abstract_m.vy": abstract_m, "override_m.vy": override_m, "caller_m.vy": caller_m}
    )

    with pytest.raises(InitializerException) as e:
        compile_code(contract, input_bundle=input_bundle)

    # Verify the error message is helpful
    expected_msg = "abstract_m.vy` is used but never initialized!"
    assert expected_msg in e.value._message
    expected_hint = "add `initializes: abstract_m`"
    assert expected_hint in e.value._hint


def test_call_to_abstract_without_uses(make_input_bundle):
    # Test that the same contract works when override_m is properly initialized
    contract = """
import abstract_m
import override_m

# uses: abstract_m
initializes: override_m

@external
def my_method() -> uint256:
    return abstract_m.bar() # Call to abstract method from un-uses-ed module
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    override_m = """
import abstract_m
initializes: abstract_m

counter: uint256

@override(abstract_m)
def bar() -> uint256:
    self.counter += 1
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m, "override_m.vy": override_m})

    with pytest.raises(StructureException) as e:
        compile_code(contract, input_bundle=input_bundle)

    expected_msg = "Cannot access abstract methods of `abstract_m`"
    assert expected_msg in e.value._message
    expected_hint = "add `uses: abstract_m` as a top-level statement to your contract"
    assert e.value._hint == expected_hint


def test_call_to_abstract_with_initializes_fails(make_input_bundle):
    """
    Test that calling an abstract method from a module you initialize fails.
    When you `initializes:` a module, you must provide overrides, so calling
    abstract methods through the abstract interface is disallowed - use `uses:` instead.
    """
    contract = """
import abstract_m

initializes: abstract_m

@external
def my_method() -> uint256:
    return abstract_m.bar()  # Cannot call abstract method when you initialize

@override(abstract_m)
def bar() -> uint256:
    return 42
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})

    with pytest.raises(CallViolation) as e:
        compile_code(contract, input_bundle=input_bundle)

    expected_msg = (
        "Abstract method `abstract_m.bar` is overridden by `self.bar`, call that instead."
    )
    assert expected_msg in str(e.value)


def test_override_non_initialized_module_fails(make_input_bundle):
    """Test that overriding from a non-initialized module fails with proper error"""
    contract = """
import foo
# Missing: initializes: foo

@override(foo)
def bar() -> uint256:
    return 42
    """

    foo = """
@abstract
def bar() -> uint256: ...
    """

    input_bundle = make_input_bundle({"foo.vy": foo})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert e.value.message == "Cannot override `foo.bar` as it is not initialized"


def test_uses_clause_does_not_allow_override(make_input_bundle):
    """Test that a module with only uses clause cannot override abstract methods"""

    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    contract = """
import abstract_module

uses: abstract_module  # Only uses, not initializes

@override(abstract_module)  # Should fail - can't override from uses-only
def foo() -> uint256:
    return 100
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "not initialized" in e.value._message


def test_module_override_without_initializing(make_input_bundle):
    """Test that a module cannot override from another module it doesn't initialize"""

    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    override_module = """
import abstract_module

uses: abstract_module  # Only uses, not initializes

@override(abstract_module)  # Should fail
def foo() -> uint256:
    return 42
    """

    contract = """
import override_module
import abstract_module

initializes: abstract_module
initializes: override_module
    """

    input_bundle = make_input_bundle(
        {"abstract_module.vy": abstract_module, "override_module.vy": override_module}
    )

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "not initialized" in e.value._message


def test_uninitialized_abstract_call_fails(make_input_bundle):
    abstract_module = """
@abstract
def foo() -> uint256: ...
    """

    override_module = """
import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo() -> uint256:
    return 42
    """

    caller_module = """
import abstract_module

uses: abstract_module

def call_foo() -> uint256:
    return abstract_module.foo()
    """

    contract = """
import override_module
import abstract_module
import caller_module

initializes: caller_module[abstract_module := abstract_module]
# initializes: override_module # Without this, we have no way of knowing which override to pick

@external
def test_foo() -> uint256:
    return caller_module.call_foo()
    """

    input_bundle = make_input_bundle(
        {
            "abstract_module.vy": abstract_module,
            "override_module.vy": override_module,
            "caller_module.vy": caller_module,
        }
    )

    with pytest.raises(InitializerException) as e:
        compile_code(contract, input_bundle=input_bundle)

    assert "abstract_module.vy` is used but never initialized!" in e.value._message
    assert "add `initializes: abstract_module`" in e.value._hint


def test_at_call_does_not_propagate_writes(make_input_bundle):
    # calling a module's function via __at__ is an external call.
    # the callee's variable writes should NOT be propagated into
    # the caller function's _variable_writes.
    other = """
counter: uint256

@external
def increment():
    self.counter += 1
    """
    main = """
import other

@external
def foo(addr: address):
    extcall other.__at__(0x0000000000000000000000000000000000000000).increment()
    """
    input_bundle = make_input_bundle({"other.vy": other})

    data = CompilerData(main, input_bundle=input_bundle)
    foo_t = data.function_signatures["foo"]
    assert len(foo_t._variable_writes) == 0


def test_at_call_does_not_propagate_reads(make_input_bundle):
    # calling a module's function via __at__ is an external call.
    # the callee's variable reads should NOT be propagated into
    # the caller function's _variable_reads.
    lib = """
counter: uint256

@external
@view
def get_counter() -> uint256:
    return self.counter
    """
    main = """
import lib

@external
@view
def foo() -> uint256:
    return staticcall lib.__at__(0x0000000000000000000000000000000000000000).get_counter()
    """
    input_bundle = make_input_bundle({"lib.vy": lib})

    data = CompilerData(main, input_bundle=input_bundle)
    foo_t = data.function_signatures["foo"]
    assert len(foo_t._variable_reads) == 0


def test_init_in_both_if_branches(make_input_bundle):
    other = """
counter: uint256

@deploy
def __init__():
    pass
    """
    main = """
import other

initializes: other

@deploy
def __init__():
    if True:
        other.__init__()
    else:
        other.__init__()
    """
    input_bundle = make_input_bundle({"other.vy": other})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_double_init_if_else(make_input_bundle):
    other = """
counter: uint256

@deploy
def __init__():
    pass
    """
    main = """
import other

initializes: other

@deploy
def __init__():
    other.__init__()
    if True:
        other.__init__()
    else:
        other.__init__()
    """
    input_bundle = make_input_bundle({"other.vy": other})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert (
        e.value.message
        == "tried to initialize `other`, but its __init__() function was already called!"
    )


def test_init_followed_by_for_loop(make_input_bundle):
    other = """
counter: uint256

@deploy
def __init__():
    pass
    """
    main = """
import other

initializes: other

@deploy
def __init__():
    other.__init__()
    for i: uint256 in range(10):
        pass
    """
    input_bundle = make_input_bundle({"other.vy": other})
    assert compile_code(main, input_bundle=input_bundle) is not None


# Shared module sources for the dependency-ordering tests below.
# Each `uses:` declaration must be backed by real state access (otherwise
# BorrowException fires before `is_initialized` ever runs).
_LIB1 = """
counter: uint256

@deploy
def __init__():
    pass
"""

_LIB2_USES_LIB1 = """
import lib1

uses: lib1

counter: uint256

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
"""

_LIB1_NO_INIT = """
counter: uint256
"""

_LIB2_NO_DEPS = """
counter: uint256

@deploy
def __init__():
    pass
"""

_LIB3_USES_BOTH = """
import lib1
import lib2

uses: (lib1, lib2)

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
    lib2.counter += 1
"""


def test_init_before_dependency(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib2.__init__()
    lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `lib2`, but it depends on the following modules "
        "which have not been initialized: lib1"
    )
    assert e.value._message == msg


def test_init_before_multiple_dependencies(make_input_bundle):
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib2
initializes: lib3[lib1 := lib1, lib2 := lib2]

@deploy
def __init__():
    lib3.__init__()
    lib1.__init__()
    lib2.__init__()
    """
    input_bundle = make_input_bundle(
        {"lib1.vy": _LIB1, "lib2.vy": _LIB2_NO_DEPS, "lib3.vy": _LIB3_USES_BOTH}
    )
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `lib3`, but it depends on the following modules "
        "which have not been initialized: lib1, lib2"
    )
    assert e.value._message == msg


def test_init_before_some_dependencies(make_input_bundle):
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib2
initializes: lib3[lib1 := lib1, lib2 := lib2]

@deploy
def __init__():
    lib1.__init__()
    lib3.__init__()
    lib2.__init__()
    """
    input_bundle = make_input_bundle(
        {"lib1.vy": _LIB1, "lib2.vy": _LIB2_NO_DEPS, "lib3.vy": _LIB3_USES_BOTH}
    )
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `lib3`, but it depends on the following modules "
        "which have not been initialized: lib2"
    )
    assert e.value._message == msg


def test_dep_init_in_only_one_if_branch_then_parent(make_input_bundle):
    # The existing "not guaranteed to be reachable" check fires before
    # the new ordering check is reached: lib1 is only initialized in
    # one branch of the `if`, which is detected when the branches merge.
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__(use: bool):
    if use:
        lib1.__init__()
    lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert "not guaranteed to be reachable" in e.value._message


def test_init_attribute_path_before_parent(make_input_bundle):
    # `lib2.lib1.__init__()` reaches lib1 through lib2's namespace; the
    # ordering rule must still treat it as a lib1 init and reject the
    # reverse order.
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib2.__init__()
    lib2.lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `lib2`, but it depends on the following modules "
        "which have not been initialized: lib1"
    )
    assert e.value._message == msg


def test_init_after_dependency(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_after_dependency_in_both_branches(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__(use: bool):
    if use:
        lib1.__init__()
        lib2.__init__()
    else:
        lib1.__init__()
        lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_chain_of_dependencies(make_input_bundle):
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib2[lib1 := lib1]
initializes: lib3[lib1 := lib1, lib2 := lib2]

@deploy
def __init__():
    lib1.__init__()
    lib2.__init__()
    lib3.__init__()
    """
    input_bundle = make_input_bundle(
        {"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1, "lib3.vy": _LIB3_USES_BOTH}
    )
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_with_dependency_without_init_function(make_input_bundle):
    # lib1 has no __init__(); it is filtered out of `initializing_nodes`.
    # The dependency loop in `is_initialized` must skip it (otherwise the
    # dict lookup would KeyError when processing `lib2.__init__()`).
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1_NO_INIT, "lib2.vy": _LIB2_USES_LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_transitive_dependency_unchecked(make_input_bundle):
    # The dependency-ordering check is one level deep: when initializing
    # lib3 (direct deps: lib1, lib2), only those direct deps' init must
    # have run. Correct order compiles cleanly.
    main = """
import lib1
import lib2
import lib3

initializes: lib1
initializes: lib2[lib1 := lib1]
initializes: lib3[lib1 := lib1, lib2 := lib2]

@deploy
def __init__():
    lib1.__init__()
    lib2.__init__()
    lib3.__init__()
    """
    input_bundle = make_input_bundle(
        {"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1, "lib3.vy": _LIB3_USES_BOTH}
    )
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_dep_initialized_by_prior_module_constructor1(make_input_bundle):
    owner = """
import lib1

initializes: lib1

counter: uint256

@deploy
def __init__():
    lib1.__init__()

@internal
def touch():
    lib1.counter += 1
"""
    user = """
import lib1

uses: lib1

counter: uint256

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
"""
    main = """
import lib1
import owner
import user

initializes: owner
initializes: user[lib1 := lib1]

@deploy
def __init__():
    owner.__init__()
    user.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "owner.vy": owner, "user.vy": user})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_transitive_init_through_nested_initializer(make_input_bundle):
    owner = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
"""
    mid = """
import owner

initializes: owner

@deploy
def __init__():
    owner.__init__()
"""
    user = """
import lib1

uses: lib1

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
"""
    main = """
import lib1
import mid
import user

initializes: mid
initializes: user[lib1 := lib1]

@deploy
def __init__():
    mid.__init__()
    user.__init__()
    """
    input_bundle = make_input_bundle(
        {"lib1.vy": _LIB1, "owner.vy": owner, "mid.vy": mid, "user.vy": user}
    )
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_used_module_adds_its_initialized_modules_to_context(make_input_bundle):
    owner = """
import lib1

initializes: lib1

counter: uint256

@deploy
def __init__():
    lib1.__init__()
"""
    user = """
import lib1

uses: lib1

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
"""
    sub = """
import lib1
import owner
import user

uses: owner
initializes: user[lib1 := lib1]

@deploy
def __init__():
    user.__init__()

@internal
def touch():
    x: uint256 = owner.counter
"""
    main = """
import lib1
import owner
import sub

initializes: owner
initializes: sub[owner := owner]

@deploy
def __init__():
    owner.__init__()
    sub.__init__()
"""
    input_bundle = make_input_bundle(
        {"lib1.vy": _LIB1, "owner.vy": owner, "user.vy": user, "sub.vy": sub}
    )
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_dep_initialized_by_prior_module_constructor(make_input_bundle):
    owner = """
import lib1

initializes: lib1

counter: uint256

@deploy
def __init__():
    lib1.__init__()

@internal
def touch():
    lib1.counter += 1
"""
    user = """
import lib1

uses: lib1

counter: uint256

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
"""
    main = """
import lib1
import owner
import user

initializes: owner
initializes: user[lib1 := lib1]

@deploy
def __init__():
    user.__init__()
    owner.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "owner.vy": owner, "user.vy": user})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = "tried to initialize `user`, "
    msg += "but it depends on the following modules which have not been initialized: lib1"
    assert e.value._message == msg


def test_init_before_no_constructor_wrapper_dependency(make_input_bundle):
    wrapper = """
import lib

uses: lib

@internal
def read_lib() -> uint256:
    return lib.counter
"""
    user = """
import wrapper

uses: wrapper

@deploy
def __init__():
    x: uint256 = wrapper.read_lib()
"""
    main = """
import lib
import wrapper
import user

initializes: lib
initializes: wrapper[lib := lib]
initializes: user[wrapper := wrapper]

@deploy
def __init__():
    user.__init__() # depends on lib through init-less `wrapper`
    lib.__init__()
    """
    input_bundle = make_input_bundle({"lib.vy": _LIB1, "wrapper.vy": wrapper, "user.vy": user})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `user`, but it depends on the following modules "
        "which have not been initialized: lib"
    )
    assert e.value._message == msg


@pytest.mark.parametrize(
    "init_body,expected_msg",
    [
        ("pass", "not initialized!"),
        ("b.__init__()", None),
        ("lib1.__init__()", "tried to initialize `lib1`, but it is not in initializer list!"),
        (
            "b.__init__()\n    lib1.__init__()",
            "tried to initialize `lib1`, but it is not in initializer list!",
        ),
    ],
)
def test_uses_counts_as_init(make_input_bundle, init_body, expected_msg):
    # b uses lib1
    # a uses lib1
    # a initializes b
    # a.__init__() must call b.__init__()
    # a.__init__() must not call lib1.__init__()
    b = """
import lib1

uses: lib1

@deploy
def __init__():
    pass

@internal
def touch():
    lib1.counter += 1
"""
    a = f"""
import lib1
import b

uses: lib1
initializes: b[lib1 := lib1]

@deploy
def __init__():
    {init_body}

@internal
def touch():
    lib1.counter += 1
    b.touch()
"""
    main = """
import lib1
import a

initializes: lib1
initializes: a[lib1 := lib1]

@deploy
def __init__():
    lib1.__init__()
    a.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "b.vy": b, "a.vy": a})
    if expected_msg is None:
        assert compile_code(main, input_bundle=input_bundle) is not None
    else:
        with pytest.raises(InitializerException) as e:
            compile_code(main, input_bundle=input_bundle)
        assert e.value._message == expected_msg


def test_duplicate_initialization_with_init_doesnt_panic(make_input_bundle):
    d = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
"""
    c = """
import lib1
import d

initializes: lib1
initializes: d

@deploy
def __init__():
    lib1.__init__()
    d.__init__()
"""
    p = """
import c

initializes: c

@deploy
def __init__():
    c.__init__()
"""
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "d.vy": d, "c.vy": c})
    with pytest.raises(InitializerException) as e:
        compile_code(p, input_bundle=input_bundle)
    assert e.value._message == "`lib1` initialized twice!"


def test_init_then_if_else_no_inner_init(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    if True:
        x: uint256 = 1
    else:
        x: uint256 = 2
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_then_if_no_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    if True:
        x: uint256 = 1
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_inside_for_loop(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    for i: uint256 in range(10):
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert "not guaranteed to be reachable" in e.value._message
    assert "present in a for loop" in e.value._message


def test_duplicate_init_in_single_branch(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    if True:
        lib1.__init__()
        lib1.__init__()
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert (
        e.value._message
        == "tried to initialize `lib1`, but its __init__() function was already called!"
    )


def test_init_only_in_if_no_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    if True:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert "not guaranteed to be reachable" in e.value._message
    assert "present only in a single branch of an if" in e.value._message


def test_nested_if_asymmetric(make_input_bundle):
    # Outer if/else is balanced (both branches reach init), but the inner if
    # only initializes in one branch — the inner asymmetry must be detected.
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    if True:
        if True:
            lib1.__init__()
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert "not guaranteed to be reachable" in e.value._message
    assert "present only in a single branch of an if" in e.value._message


def test_raise_in_then_init_in_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        raise "nope"
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_in_then_raise_in_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
    else:
        raise "nope"
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_no_init_in_then_raise_in_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        pass
    else:
        raise "nope"
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_both_branches_raise_with_initializer(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        raise "nope"
    else:
        raise "still nope"
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_then_raise_in_one_branch(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
        raise "nope"
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_nested_if_both_branches_raise_then_outer_else_inits(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond1: bool, cond2: bool):
    if cond1:
        if cond2:
            raise "nope"
        else:
            raise "still nope"
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_body_only_raise_with_initializer(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    raise "nope"
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_body_only_raise_no_initializers(make_input_bundle):
    main = """
@deploy
def __init__():
    raise "nope"
    """
    assert compile_code(main) is not None


def test_raw_revert_in_then_init_in_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        raw_revert(b"nope")
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_no_init_in_then_raw_revert_in_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        pass
    else:
        raw_revert(b"nope")
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_init_body_only_raw_revert_with_initializer(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    raw_revert(b"nope")
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_selfdestruct_in_then_init_in_else(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        selfdestruct(msg.sender)
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_init_body_only_selfdestruct_with_initializer(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    selfdestruct(msg.sender)
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_raise_in_for_loop_body_alone(make_input_bundle):
    main = """
@deploy
def __init__():
    for i: uint256 in range(10):
        raise "nope"
    """
    assert compile_code(main) is not None


def test_init_then_for_loop_with_raise(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    for i: uint256 in range(10):
        raise "nope"
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_dependency_ordering_preserved_with_raise_wildcard(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        raise "nope"
    else:
        lib2.__init__()
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `lib2`, but it depends on the following modules "
        "which have not been initialized: lib1"
    )
    assert e.value._message == msg


def test_dependency_init_split_across_raise_branches(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        raise "nope"
    else:
        lib1.__init__()
        lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_dep_init_after_raise_wildcard_if(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib1
initializes: lib2[lib1 := lib1]

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
    else:
        raise "nope"
    lib2.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_nested_if_inner_raise_as_wildcard(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond1: bool, cond2: bool):
    if cond1:
        if cond2:
            raise "nope"
        else:
            lib1.__init__()
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_assert_false_is_not_a_wildcard(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        assert False, "nope"
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert "not guaranteed to be reachable" in e.value._message
    assert "present only in a single branch of an if" in e.value._message


def test_return_at_end_after_init(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_bare_return_no_initializers(make_input_bundle):
    main = """
@deploy
def __init__():
    return
    """
    assert compile_code(main) is not None


def test_return_before_required_init(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_init_after_return_is_dead(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    return
    lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "Unreachable code!"


def test_return_in_then_after_init_else_inits(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
        return
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_return_in_then_without_init_else_inits(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        return
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_both_branches_return_after_init(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
        return
    else:
        lib1.__init__()
        return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_both_branches_return_without_init(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        return
    else:
        return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_return_in_then_without_else_init_after(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    if True:
        return
    lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_return_after_if_validates_total(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
    else:
        lib1.__init__()
    return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_nested_if_return_in_inner_branch_without_init(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__(cond1: bool, cond2: bool):
    if cond1:
        if cond2:
            return
        else:
            lib1.__init__()
    else:
        lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_return_in_for_body_no_initializers(make_input_bundle):
    main = """
@deploy
def __init__():
    for i: uint256 in range(10):
        return
    """
    assert compile_code(main) is not None


def test_return_in_for_body_required_init_missing(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    for i: uint256 in range(10):
        return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_return_and_init_in_for_body(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    for i: uint256 in range(10):
        lib1.__init__()
        return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    assert e.value._message == "not initialized!"


def test_init_then_for_loop_with_return(make_input_bundle):
    main = """
import lib1

initializes: lib1

@deploy
def __init__():
    lib1.__init__()
    for i: uint256 in range(10):
        return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_return_after_dependent_before_dependency(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib2[lib1 := lib1]
initializes: lib1

@deploy
def __init__():
    lib2.__init__()
    return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    with pytest.raises(InitializerException) as e:
        compile_code(main, input_bundle=input_bundle)
    msg = (
        "tried to initialize `lib2`, but it depends on the following modules "
        "which have not been initialized: lib1"
    )
    assert e.value._message == msg


def test_return_in_branch_with_correct_dep_order(make_input_bundle):
    main = """
import lib1
import lib2

initializes: lib1
initializes: lib2[lib1 := lib1]

@deploy
def __init__(cond: bool):
    if cond:
        lib1.__init__()
        lib2.__init__()
        return
    else:
        lib1.__init__()
        lib2.__init__()
        return
    """
    input_bundle = make_input_bundle({"lib1.vy": _LIB1, "lib2.vy": _LIB2_USES_LIB1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_for_loop_with_guarded_init_and_return_then_raise(make_input_bundle):
    lib = """
counter: uint256

@deploy
def __init__(x: uint256):
    self.counter = x
    """
    main = """
import lib

initializes: lib

@deploy
def __init__(xs: DynArray[uint256, 10]):
    for x: uint256 in xs:
        if x > 0:
            lib.__init__(x)
            return
    raise "no valid x in xs"
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    assert compile_code(main, input_bundle=input_bundle) is not None
