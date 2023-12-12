import pytest

from vyper import compiler
from vyper.exceptions import ImportCycle, CallViolation


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


def test_transitive_import(get_contract, make_input_bundle):
    a = """
@internal
def foo() -> uint256:
    return 1
    """
    b = """
import a

@internal
def bar() -> uint256:
    return a.foo() + 1
    """
    c = """
import b

@external
def baz() -> uint256:
    return b.bar() + 1
    """
    # more complicated call graph, with `a` imported twice.
    d = """
import b
import a

@external
def qux() -> uint256:
    s: uint256 = a.foo()
    return s + b.bar() + 1
    """
    input_bundle = make_input_bundle({"a.vy": a, "b.vy": b, "c.vy": c, "d.vy": d})

    contract = get_contract(c, input_bundle=input_bundle)
    assert contract.baz() == 3
    contract = get_contract(d, input_bundle=input_bundle)
    assert contract.qux() == 4


def test_cannot_call_library_external_functions(make_input_bundle):
    library_source = """
@external
def foo():
    pass
    """
    contract_source = """
import library

@external
def bar():
    library.foo()
    """
    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})
    with pytest.raises(CallViolation):
        compiler.compile_code(contract_source, input_bundle=input_bundle)


def test_library_external_functions_not_in_abi(get_contract, make_input_bundle):
    library_source = """
@external
def foo():
    pass
    """
    contract_source = """
import library

@external
def bar():
    pass
    """
    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})
    c = get_contract(contract_source, input_bundle=input_bundle)
    assert not hasattr(c, "foo")
