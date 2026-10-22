import pytest

from vyper.compiler import compile_code
from vyper.exceptions import InterfaceViolation, StructureException


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
def test_implements_with_public_interface(var_decl, iface_method, store_stmt):
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
    compile_code(main)


@pytest.mark.parametrize(
    "iface_return,impl_return,return_stmt",
    [
        pytest.param("address", "IERC20", "return self.asset", id="address"),
        pytest.param(
            "address[3]", "IERC20[3]", "return [self.asset, self.asset, self.asset]", id="sarray"
        ),
        pytest.param(
            "DynArray[address, 3]", "DynArray[IERC20, 3]", "return [self.asset]", id="dynarray"
        ),
        pytest.param("(address, uint256)", "(IERC20, uint256)", "return self.asset, 1", id="tuple"),
        pytest.param(
            "DynArray[address[2], 3]",
            "DynArray[IERC20[2], 3]",
            "return [[self.asset, self.asset]]",
            id="nested_dynarray_sarray",
        ),
        pytest.param(
            "(DynArray[address, 2], address[1])",
            "(DynArray[IERC20, 2], IERC20[1])",
            "return [self.asset], [self.asset]",
            id="nested_tuple",
        ),
    ],
)
def test_implements_interface_for_address_in_return_type(iface_return, impl_return, return_stmt):
    main = f"""
from ethereum.ercs import IERC20

interface IAsset:
    def foo() -> {iface_return}: view

implements: IAsset

asset: IERC20

@external
@view
def foo() -> {impl_return}:
    {return_stmt}
    """
    # the interface's own (address-based) signature, for comparison
    reference = f"""
asset: address

@external
@view
def foo() -> {iface_return}:
    {return_stmt}
    """

    # must not change the external signature
    assert (
        compile_code(main, output_formats=["abi"])["abi"]
        == compile_code(reference, output_formats=["abi"])["abi"]
    )


@pytest.mark.parametrize(
    "iface_arg,impl_arg,expected_sig",
    [
        ("address", "IERC20", "foo(address)"),
        ("IERC20", "address", "foo(interface vyper/builtins/interfaces/IERC20.vyi)"),
    ],
)
def test_implements_interface_for_address_not_in_argument_type(iface_arg, impl_arg, expected_sig):
    # weak subtyping is deliberately not applied to arguments
    main = f"""
from ethereum.ercs import IERC20

interface IAsset:
    def foo(x: {iface_arg}): nonpayable

implements: IAsset

@external
def foo(x: {impl_arg}):
    pass
    """
    with pytest.raises(InterfaceViolation) as e:
        compile_code(main)

    assert e.value._message == (
        f"Contract does not implement all interface functions: {expected_sig}"
    )
