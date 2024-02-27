import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from vyper import compiler
from vyper.exceptions import (
    CallViolation,
    DuplicateImport,
    ImportCycle,
    StructureException,
    TypeMismatch,
)

# test modules which have no variables - "libraries"


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


# test we can have a function in the library with the same name as
# in the main contract
def test_library_function_same_name(get_contract, make_input_bundle):
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


def test_library_structs(get_contract, make_input_bundle):
    library_source = """
struct SomeStruct:
    x: uint256

@internal
def foo() -> SomeStruct:
    return SomeStruct(x=1)
    """
    contract_source = """
import library

@external
def bar(s: library.SomeStruct):
    pass

@external
def baz() -> library.SomeStruct:
    return library.SomeStruct(x=2)

@external
def qux() -> library.SomeStruct:
    return library.foo()
    """
    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})
    c = get_contract(contract_source, input_bundle=input_bundle)

    assert c.bar((1,)) == []

    assert c.baz() == (2,)
    assert c.qux() == (1,)


# test calls to library functions in statement position
def test_library_statement_calls(get_contract, make_input_bundle, tx_failed):
    library_source = """
from ethereum.ercs import IERC20
@internal
def check_adds_to_ten(x: uint256, y: uint256):
    assert x + y == 10
    """
    contract_source = """
import library

counter: public(uint256)

@external
def foo(x: uint256):
    library.check_adds_to_ten(3, x)
    self.counter = x
    """
    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})

    c = get_contract(contract_source, input_bundle=input_bundle)

    c.foo(7, transact={})

    assert c.counter() == 7

    with tx_failed():
        c.foo(8)


def test_library_is_typechecked(make_input_bundle):
    library_source = """
@internal
def foo():
    asdlkfjasdflkajsdf
    """
    contract_source = """
import library
    """

    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})
    with pytest.raises(StructureException):
        compiler.compile_code(contract_source, input_bundle=input_bundle)


def test_library_is_typechecked2(make_input_bundle):
    # check that we typecheck against imported function signatures
    library_source = """
@internal
def foo() -> uint256:
    return 1
    """
    contract_source = """
import library

@external
def foo() -> bytes32:
    return library.foo()
    """

    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})
    with pytest.raises(TypeMismatch):
        compiler.compile_code(contract_source, input_bundle=input_bundle)


def test_reject_duplicate_imports(make_input_bundle):
    library_source = """
    """

    contract_source = """
import library
import library as library2
    """
    input_bundle = make_input_bundle({"library.vy": library_source, "contract.vy": contract_source})
    with pytest.raises(DuplicateImport):
        compiler.compile_code(contract_source, input_bundle=input_bundle)


def test_nested_module_access(get_contract, make_input_bundle):
    lib1 = """
import lib2

@internal
def lib2_foo() -> uint256:
    return lib2.foo()
    """
    lib2 = """
@internal
def foo() -> uint256:
    return 1337
    """

    main = """
import lib1
import lib2

@external
def lib1_foo() -> uint256:
    return lib1.lib2_foo()

@external
def lib2_foo() -> uint256:
    return lib1.lib2.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.lib1_foo() == c.lib2_foo() == 1337


_int_127 = st.integers(min_value=0, max_value=127)
_bytes_128 = st.binary(min_size=0, max_size=128)


def test_slice_builtin(get_contract, make_input_bundle):
    lib = """
@internal
def slice_input(x: Bytes[128], start: uint256, length: uint256) -> Bytes[128]:
    return slice(x, start, length)
    """

    main = """
import lib
@external
def lib_slice_input(x: Bytes[128], start: uint256, length: uint256) -> Bytes[128]:
    return lib.slice_input(x, start, length)

@external
def slice_input(x: Bytes[128], start: uint256, length: uint256) -> Bytes[128]:
    return slice(x, start, length)
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    c = get_contract(main, input_bundle=input_bundle)

    # use an inner test so that we can cache the result of get_contract()
    @given(start=_int_127, length=_int_127, bytesdata=_bytes_128)
    @settings(max_examples=100)
    def _test(bytesdata, start, length):
        # surjectively map start into allowable range
        if start > len(bytesdata):
            start = start % (len(bytesdata) or 1)
        # surjectively map length into allowable range
        if length > (len(bytesdata) - start):
            length = length % ((len(bytesdata) - start) or 1)
        main_result = c.slice_input(bytesdata, start, length)
        library_result = c.lib_slice_input(bytesdata, start, length)
        assert main_result == library_result == bytesdata[start : start + length]

    _test()
