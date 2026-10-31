import pytest

from vyper.compiler import compile_code
from vyper.exceptions import ArgumentException, StructureException


valid_list = [
    # basic method_id_of access
    """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def foo() -> bytes4:
    return method_id_of(Foo.transfer)
    """,
    # use in raw_call
    """
interface Foo:
    def bar(x: uint256) -> uint256: view

@external
def foo():
    x: Bytes[32] = raw_call(
        msg.sender,
        concat(method_id_of(Foo.bar), convert(1, bytes32)),
        max_outsize=32
    )
    """,
]


@pytest.mark.parametrize("code", valid_list)
def test_method_id_of_pass(code):
    assert compile_code(code) is not None


def test_method_id_of_not_a_function():
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def foo() -> bytes4:
    return method_id_of(Foo)
    """
    with pytest.raises((ArgumentException, StructureException)):
        compile_code(code)


def test_method_id_of_string_not_accepted():
    code = """
@external
def foo() -> bytes4:
    return method_id_of("transfer(address,uint256)")
    """
    with pytest.raises((ArgumentException, StructureException)):
        compile_code(code)


def test_method_id_of_n_optional_args_out_of_range(make_input_bundle):
    iface_code = """
@external
def take(auction_id: uint256, max_take_amount: uint256 = ...) -> uint256:
    ...
    """
    input_bundle = make_input_bundle({"ifoo.vyi": iface_code})

    code = """
import ifoo as IFoo

@external
def foo() -> bytes4:
    return method_id_of(IFoo.take, n_optional_args=5)
    """
    with pytest.raises(ArgumentException):
        compile_code(code, input_bundle=input_bundle)


def test_method_id_of_n_optional_args_zero_no_defaults():
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def foo() -> bytes4:
    return method_id_of(Foo.transfer, n_optional_args=0)
    """
    assert compile_code(code) is not None


def test_method_id_of_n_optional_args_no_defaults():
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def foo() -> bytes4:
    return method_id_of(Foo.transfer, n_optional_args=1)
    """
    with pytest.raises(ArgumentException):
        compile_code(code)


def test_method_id_of_default_args(make_input_bundle):
    iface_code = """
@external
def take(
    auction_id: uint256,
    max_take_amount: uint256 = ...,
) -> uint256:
    ...
    """
    input_bundle = make_input_bundle({"ifoo.vyi": iface_code})

    code = """
import ifoo as IFoo

@external
def foo() -> bytes4:
    return method_id_of(IFoo.take)
    """
    assert compile_code(code, input_bundle=input_bundle) is not None


def test_interface_function_not_valid_as_type():
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

x: Foo.transfer
    """
    with pytest.raises(StructureException):
        compile_code(code)
