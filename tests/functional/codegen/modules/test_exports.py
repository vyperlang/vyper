import pytest

from vyper.compiler import compile_code
from vyper.utils import method_id


def test_simple_export(make_input_bundle, get_contract):
    lib1 = """
@external
def foo() -> uint256:
    return 5
    """
    main = """
import lib1

exports: lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5


def test_export_with_state(make_input_bundle, get_contract):
    lib1 = """
counter: uint256

@external
def foo() -> uint256:
    return self.counter
    """
    main = """
import lib1

initializes: lib1
exports: lib1.foo

@deploy
def __init__():
    lib1.counter = 99
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 99


def test_variable_decl_exports(make_input_bundle, get_contract):
    lib1 = """
counter: public(uint256)
FOO: public(immutable(uint256))
BAR: public(constant(uint256)) = 3

@deploy
def __init__():
    self.counter = 1
    FOO = 2
    """
    main = """
import lib1

initializes: lib1
exports: (
    lib1.counter,
    lib1.FOO,
    lib1.BAR,
)

@deploy
def __init__():
    lib1.__init__()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.counter() == 1
    assert c.FOO() == 2
    assert c.BAR() == 3


def test_not_exported(make_input_bundle, get_contract):
    # test that non-exported functions are not in the selector table
    lib1 = """
@external
def foo() -> uint256:
    return 100

@external
def bar() -> uint256:
    return 101
    """
    main = """
import lib1

exports: lib1.foo

@external
def __default__() -> uint256:
    return 127
    """
    caller_code = """
interface Foo:
    def foo() -> uint256: nonpayable
    def bar() -> uint256: nonpayable

@external
def call_bar(foo: Foo) -> uint256:
    return extcall foo.bar()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    caller = get_contract(caller_code)

    assert caller.call_bar(c.address) == 127  # default return value


def test_nested_export(make_input_bundle, get_contract):
    lib1 = """
@external
def foo() -> uint256:
    return 5
    """
    lib2 = """
import lib1
    """
    main = """
import lib2

exports: lib2.lib1.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5


def test_transitive_export(make_input_bundle, get_contract):
    lib1 = """
@external
def foo() -> uint256:
    return 5
    """
    lib2 = """
import lib1
exports: lib1.foo
    """
    main = """
import lib2

exports: lib2.foo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)

    assert c.foo() == 5


@pytest.fixture
def simple_library(make_input_bundle):
    ifoo = """
@external
def foo() -> uint256:
    ...

@external
def bar() -> uint256:
    ...
    """
    ibar = """
@external
def bar() -> uint256:
    ...

@external
def qux() -> uint256:
    ...
    """
    lib1 = """
import ifoo
import ibar

implements: ifoo
implements: ibar

@external
def foo() -> uint256:
    return 1

@external
def bar() -> uint256:
    return 2

@external
def qux() -> uint256:
    return 3
    """
    return make_input_bundle({"lib1.vy": lib1, "ifoo.vyi": ifoo, "ibar.vyi": ibar})


@pytest.fixture
def send_failing_tx_to_signature(env, tx_failed):
    def _send_transaction(c, method_sig):
        data = method_id(method_sig)
        with tx_failed():
            env.message_call(c.address, data=data)

    return _send_transaction


def test_exports_interface_simple(get_contract, simple_library):
    main = """
import lib1

exports: lib1.__interface__
    """
    c = get_contract(main, input_bundle=simple_library)
    assert c.foo() == 1
    assert c.bar() == 2
    assert c.qux() == 3


def test_exports_interface2(get_contract, send_failing_tx_to_signature, simple_library):
    main = """
import lib1

exports: lib1.ifoo
    """
    out = compile_code(
        main, output_formats=["abi"], contract_path="main.vy", input_bundle=simple_library
    )
    fnames = [item["name"] for item in out["abi"]]
    assert fnames == ["foo", "bar"]

    c = get_contract(main, input_bundle=simple_library)
    assert c.foo() == 1
    assert c.bar() == 2
    assert not hasattr(c, "qux")
    send_failing_tx_to_signature(c, "qux()")


def test_exported_fun_part_of_interface(get_contract, make_input_bundle):
    main = """
import lib2

exports: lib2.__interface__
    """
    lib1 = """
@external
def bar() -> uint256:
    return 1
    """
    lib2 = """
import lib1

@external
def foo() -> uint256:
    return 2

exports: lib1.bar
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)
    assert c.bar() == 1
    assert c.foo() == 2


def test_imported_module_not_part_of_interface(
    send_failing_tx_to_signature, get_contract, make_input_bundle
):
    main = """
import lib2

exports: lib2.__interface__
    """
    lib1 = """
@external
def bar() -> uint256:
    return 1
    """
    lib2 = """
import lib1

@external
def foo() -> uint256:
    return 2
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 2
    send_failing_tx_to_signature(c, "bar()")


def test_export_unimplemented_function(
    send_failing_tx_to_signature, get_contract, make_input_bundle
):
    ifoo = """
@external
def foo() -> uint256:
    ...
    """
    lib1 = """
import ifoo
implements: ifoo

@external
def foo() -> uint256:
    return 1

@external
def bar() -> uint256:
    return 2
    """
    main = """
import lib1

exports: lib1.ifoo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "ifoo.vyi": ifoo})
    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 1
    send_failing_tx_to_signature(c, "bar()")


# sanity check that when multiple modules implement an interface, the
# correct one (specified by the user) gets selected for export.
def test_export_interface_multiple_choices(get_contract, make_input_bundle):
    ifoo = """
@external
def foo() -> uint256:
    ...
    """
    lib1 = """
import ifoo
implements: ifoo

@external
def foo() -> uint256:
    return 1
    """
    lib2 = """
import ifoo
implements: ifoo

@external
def foo() -> uint256:
    return 2
    """
    main = """
import lib1
import lib2

exports: lib1.ifoo
    """
    main2 = """
import lib1
import lib2

exports: lib2.ifoo
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2, "ifoo.vyi": ifoo})

    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 1

    c = get_contract(main2, input_bundle=input_bundle)
    assert c.foo() == 2


def test_export_module_with_init(get_contract, make_input_bundle):
    lib1 = """
@deploy
def __init__():
    pass

@external
def foo() -> uint256:
    return 1
    """
    main = """
import lib1

exports: lib1.__interface__
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 1


def test_export_module_with_getter(get_contract, make_input_bundle):
    lib1 = """
counter: public(uint256)

@external
def foo():
    self.counter += 1
    """
    main = """
import lib1

initializes: lib1
exports: lib1.__interface__

@deploy
def __init__():
    lib1.counter = 100
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    assert c.counter() == 100
    c.foo()
    assert c.counter() == 101


def test_export_module_with_default(env, get_contract, make_input_bundle):
    lib1 = """
counter: public(uint256)

@external
def foo() -> uint256:
    return 1

@external
def __default__():
    self.counter += 1
    """
    main = """
import lib1
initializes: lib1

@deploy
def __init__():
    lib1.counter = 5

exports: lib1.__interface__
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == 1
    assert c.counter() == 5
    # call `c.__default__()`
    env.message_call(c.address)
    assert c.counter() == 6
