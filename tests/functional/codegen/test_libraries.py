import pytest

from vyper import compiler
from vyper.exceptions import ImportCycle


def test_simple_library(get_contract, make_input_bundle, w3):
    library_source = """
@internal
def foo() -> uint256:
    return block.number + 1
    """
    main = """
import library

@external
def bar() -> uint256:
    return library.foo() - 1
    """
    input_bundle = make_input_bundle({"library.vy": library_source})

    c = get_contract(main, input_bundle=input_bundle)

    assert c.bar() == w3.eth.block_number


# is this the best place for this?
def test_import_cycle(make_input_bundle):
    code_a = "import b\n"
    code_b = "import a\n"

    input_bundle = make_input_bundle({"a.vy": code_a, "b.vy": code_b})

    with pytest.raises(ImportCycle):
        compiler.compile_code(code_a, input_bundle=input_bundle)


def test_function_name_collision(get_contract, make_input_bundle):
    library = """
@internal
def foo() -> uint256:
    return 10
    """

    main = """
import library

@internal
def foo() -> uint256:
    return 100

@external
def self_foo() -> uint256:
    return self.foo()

@external
def library_foo() -> uint256:
    return library.foo()
    """

    input_bundle = make_input_bundle({"library.vy": library})

    c = get_contract(main, input_bundle=input_bundle)

    assert c.self_foo() == 100
    assert c.library_foo() == 10
