import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException


def test_implements_from_vyi(make_input_bundle):
    vyi = """
@external
def foo():
    ...
    """
    lib1 = """
import some_interface
    """
    main = """
import lib1

implements: lib1.some_interface

@external
def foo():  # implementation
    pass
    """
    input_bundle = make_input_bundle({"some_interface.vyi": vyi, "lib1.vy": lib1})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_implements_from_vyi2(make_input_bundle):
    # test implements via nested imported vyi file
    vyi = """
@external
def foo():
    ...
    """
    lib1 = """
import some_interface
    """
    lib2 = """
import lib1
    """
    main = """
import lib2

implements: lib2.lib1.some_interface

@external
def foo():  # implementation
    pass
    """
    input_bundle = make_input_bundle({"some_interface.vyi": vyi, "lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_duplicate_implements_in_same_statement_fails(make_input_bundle):
    vyi = """
@external
def foo():
    ...
    """
    main = """
import some_interface

implements: (
    some_interface,
    some_interface,
)

@external
def foo():  # implementation
    pass
    """
    input_bundle = make_input_bundle({"some_interface.vyi": vyi})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "some_interface implemented more than once"
    assert e.value._hint is None


def test_duplicate_implements_in_different_statement_fails(make_input_bundle):
    vyi = """
@external
def foo():
    ...
    """
    main = """
import some_interface

implements: some_interface
implements: some_interface

@external
def foo():  # implementation
    pass
    """
    input_bundle = make_input_bundle({"some_interface.vyi": vyi})

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "some_interface implemented more than once"
    assert e.value._hint is None


def test_duplicate_implements_in_different_statement_with_mixed_syntax_fails(make_input_bundle):
    some_interface = """
@external
def foo():
    ...
    """
    other_interface = """
@external
def bar():
    ...
    """
    main = """
import some_interface
import other_interface

implements: some_interface
implements: (
    other_interface,
    some_interface,
)

@external
def foo():  # implementation
    pass

@external
def bar():  # implementation
    pass
    """
    input_bundle = make_input_bundle(
        {"some_interface.vyi": some_interface, "other_interface.vyi": other_interface}
    )

    with pytest.raises(StructureException) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "some_interface implemented more than once"
    assert e.value._hint is None


@pytest.mark.parametrize(
    "var_decl,iface_method,store_stmt",
    [
        pytest.param(
            "foo: public(IERC20)", "def foo() -> address: view", "self.foo = asset_", id="storage"
        ),
        pytest.param(  # GH issue 3954
            "foo: public(immutable(IERC20))",
            "def foo() -> address: view",
            "self.foo = asset_",
            id="immutable",
        ),
        pytest.param(
            "foo: public(HashMap[uint256, IERC20])",
            "def foo(k: uint256) -> address: view",
            "self.foo[7] = asset_",
            id="hashmap",
        ),
        pytest.param(
            "foo: public(DynArray[IERC20, 3])",
            "def foo(i: uint256) -> address: view",
            "self.foo.append(asset_)",
            id="dynarray",
        ),
        pytest.param(  # GH issue 4721
            "foo: public(IERC20)",
            "def foo() -> IERC20: view",
            "self.foo = asset_",
            id="interface_return",
        ),
    ],
)
def test_implements_with_public_interface(env, var_decl, iface_method, store_stmt):
    """
    Tests that `var_decl` correctly implements `iface_method`

    For example `foo: public(IERC20)` implements `def foo() -> address: view`
    """

    main = f"""
from ethereum.ercs import IERC20

{var_decl}

interface IAsset:
    {iface_method}

implements: IAsset

@deploy
def __init__(asset_: IERC20):
    {store_stmt}
    """
    some_address = env.accounts[1]
    compile_code(main, some_address)
