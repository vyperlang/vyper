import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException


valid_list = [
    # basic method_id access
    """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def foo() -> bytes4:
    return Foo.transfer.method_id
    """,
    # use in raw_call
    """
interface Foo:
    def bar(x: uint256) -> uint256: view

@external
def foo():
    x: Bytes[32] = raw_call(
        msg.sender,
        concat(Foo.bar.method_id, convert(1, bytes32)),
        max_outsize=32
    )
    """,
]


@pytest.mark.parametrize("code", valid_list)
def test_interface_method_id_pass(code):
    assert compile_code(code) is not None


def test_interface_method_id_no_instance_access():
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def foo(addr: address) -> bytes4:
    return Foo(addr).transfer.method_id
    """
    with pytest.raises(StructureException):
        compile_code(code)


def test_interface_method_id_default_args(make_input_bundle):
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
    return IFoo.take.method_id
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
