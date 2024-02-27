import pytest

from vyper.compiler import compile_code
from vyper.exceptions import ImmutableViolation, NamespaceCollision, StructureException


def test_exports_no_uses(make_input_bundle):
    lib1 = """
counter: uint256

@external
def get_counter() -> uint256:
    self.counter += 1
    return self.counter
    """
    main = """
import lib1
exports: lib1.get_counter
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value.hint == expected_hint


def test_exports_no_uses_variable(make_input_bundle):
    lib1 = """
counter: public(uint256)
    """
    main = """
import lib1
exports: lib1.counter
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(ImmutableViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "Cannot access `lib1` state!"

    expected_hint = "add `uses: lib1` or `initializes: lib1` as a "
    expected_hint += "top-level statement to your contract"
    assert e.value.hint == expected_hint


def test_exports_uses_variable(make_input_bundle):
    lib1 = """
counter: public(uint256)
    """
    main = """
import lib1

exports: lib1.counter
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_exports_uses(make_input_bundle):
    lib1 = """
counter: uint256

@external
def get_counter() -> uint256:
    self.counter += 1
    return self.counter
    """
    main = """
import lib1

exports: lib1.get_counter
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    assert compile_code(main, input_bundle=input_bundle) is not None


# test that exporting can satisfy an implements constraint
# use a mix of public variables and functions
def test_exports_implements(make_input_bundle):
    token_interface = """
@external
@view
def totalSupply() -> uint256:
    ...

@external
@view
def balanceOf(addr: address) -> uint256:
    ...

@external
def transfer(receiver: address, amount: uint256):
    ...
    """
    lib1 = """
import itoken

implements: itoken

@deploy
def __init__(initial_supply: uint256):
    self.totalSupply = initial_supply
    self.balanceOf[msg.sender] = initial_supply

totalSupply: public(uint256)
balanceOf: public(HashMap[address, uint256])

@external
def transfer(receiver: address, amount: uint256):
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[receiver] += amount
    """
    main = """
import tokenlib
import itoken

implements: itoken
exports: (tokenlib.totalSupply, tokenlib.balanceOf, tokenlib.transfer)

initializes: tokenlib

@deploy
def __init__():
    tokenlib.__init__(100_000_000)
    """
    input_bundle = make_input_bundle({"tokenlib.vy": lib1, "itoken.vyi": token_interface})
    assert compile_code(main, input_bundle=input_bundle) is not None


# test that exporting can satisfy an implements constraint
# use a mix of local and imported functions
def test_exports_implements2(make_input_bundle):
    ifoobar = """
@external
def foo():
    ...

@external
def bar():
    ...
    """
    lib1 = """
import ifoobar

implements: ifoobar

counter: uint256

@external
def foo():
    pass

@external
def bar():
    self.counter += 1
    """
    main = """
import lib1
import ifoobar

implements: ifoobar
exports: lib1.foo

initializes: lib1

# for fun, export a different function with the same name
@external
def bar():
    lib1.counter += 2
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "ifoobar.vyi": ifoobar})
    assert compile_code(main, input_bundle=input_bundle) is not None


def test_function_name_collisions(make_input_bundle):
    lib1 = """
@external
def foo():
    pass
    """
    main = """
import lib1

exports: lib1.foo

@external
def foo():
    x: uint256 = 12345
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(NamespaceCollision) as e:
        # TODO: make the error message reference the export
        compile_code(main, contract_path="main.vy", input_bundle=input_bundle)

    assert e.value._message == "Member 'foo' already exists in self"

    assert e.value.annotations[0].lineno == 4
    assert e.value.annotations[0].node_source_code == "lib1.foo"
    assert e.value.annotations[0].module_node.path == "main.vy"

    assert e.value.prev_decl.lineno == 7
    assert e.value.prev_decl.node_source_code.startswith("def foo():")
    assert e.value.prev_decl.module_node.path == "main.vy"


def test_duplicate_exports(make_input_bundle):
    lib1 = """
@external
def foo():
    pass

@external
def bar():
    pass
    """
    main = """
import lib1

exports: lib1.foo
exports: lib1.bar
exports: lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(StructureException) as e:
        # TODO: make the error message reference the export
        compile_code(main, contract_path="main.vy", input_bundle=input_bundle)

    assert e.value._message == "already exported!"

    assert e.value.annotations[0].lineno == 6
    assert e.value.annotations[0].node_source_code == "lib1.foo"
    assert e.value.annotations[0].module_node.path == "main.vy"

    assert e.value.prev_decl.lineno == 4
    assert e.value.prev_decl.node_source_code == "lib1.foo"
    assert e.value.prev_decl.module_node.path == "main.vy"


def test_duplicate_exports_tuple(make_input_bundle):
    lib1 = """
@external
def foo():
    pass

@external
def bar():
    pass
    """
    main = """
import lib1

exports: (lib1.foo, lib1.bar, lib1.foo)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(StructureException) as e:
        # TODO: make the error message reference the export
        compile_code(main, contract_path="main.vy", input_bundle=input_bundle)

    assert e.value._message == "already exported!"

    assert e.value.annotations[0].lineno == 4
    assert e.value.annotations[0].col_offset == 30
    assert e.value.annotations[0].node_source_code == "lib1.foo"
    assert e.value.annotations[0].module_node.path == "main.vy"

    assert e.value.prev_decl.lineno == 4
    assert e.value.prev_decl.col_offset == 10
    assert e.value.prev_decl.node_source_code == "lib1.foo"
    assert e.value.prev_decl.module_node.path == "main.vy"


def test_duplicate_exports_tuple2(make_input_bundle):
    lib1 = """
@external
def foo():
    pass

@external
def bar():
    pass
    """
    main = """
import lib1

exports: lib1.foo
exports: (lib1.bar, lib1.foo)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    with pytest.raises(StructureException) as e:
        # TODO: make the error message reference the export
        compile_code(main, contract_path="main.vy", input_bundle=input_bundle)

    assert e.value._message == "already exported!"

    assert e.value.annotations[0].lineno == 5
    assert e.value.annotations[0].col_offset == 20
    assert e.value.annotations[0].node_source_code == "lib1.foo"
    assert e.value.annotations[0].module_node.path == "main.vy"

    assert e.value.prev_decl.lineno == 4
    assert e.value.prev_decl.col_offset == 9
    assert e.value.prev_decl.node_source_code == "lib1.foo"
    assert e.value.prev_decl.module_node.path == "main.vy"
