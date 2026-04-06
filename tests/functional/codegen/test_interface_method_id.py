import pytest

from vyper.utils import method_id


def test_interface_method_id_basic(get_contract):
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def get_method_id() -> bytes4:
    return Foo.transfer.method_id
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("transfer(address,uint256)")
    assert result == expected


def test_interface_method_id_view_function(get_contract):
    code = """
interface Foo:
    def balanceOf(owner: address) -> uint256: view

@external
def get_method_id() -> bytes4:
    return Foo.balanceOf.method_id
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("balanceOf(address)")
    assert result == expected


def test_interface_method_id_no_args(get_contract):
    code = """
interface Foo:
    def totalSupply() -> uint256: view

@external
def get_method_id() -> bytes4:
    return Foo.totalSupply.method_id
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("totalSupply()")
    assert result == expected


def test_interface_method_id_in_raw_call(get_contract, env):
    called_code = """
@external
def double(x: uint256) -> uint256:
    return x * 2
    """
    caller_code = """
interface Doubler:
    def double(x: uint256) -> uint256: view

@external
def call_double(target: address, x: uint256) -> uint256:
    response: Bytes[32] = raw_call(
        target,
        concat(Doubler.double.method_id, convert(x, bytes32)),
        max_outsize=32
    )
    return convert(convert(response, bytes32), uint256)
    """
    callee = get_contract(called_code)
    caller = get_contract(caller_code)
    assert caller.call_double(callee.address, 5) == 10


def test_interface_method_id_assign_to_variable(get_contract):
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def get_method_id() -> bytes4:
    m: bytes4 = Foo.transfer.method_id
    return m
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("transfer(address,uint256)")
    assert result == expected


def test_interface_method_id_compare(get_contract):
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def check() -> bool:
    return Foo.transfer.method_id == method_id('transfer(address,uint256)', output_type=bytes4)
    """
    c = get_contract(code)
    assert c.check() is True


def test_interface_method_id_default_args(get_contract, make_input_bundle):
    iface_code = """
@external
def take(auction_id: uint256, max_take_amount: uint256 = ...) -> uint256:
    ...
    """
    input_bundle = make_input_bundle({"ifoo.vyi": iface_code})

    code = """
import ifoo as IFoo

@external
def get_method_id() -> bytes4:
    return IFoo.take.method_id
    """
    c = get_contract(code, input_bundle=input_bundle)
    result = c.get_method_id()
    # should return the full signature selector (all args)
    expected = method_id("take(uint256,uint256)")
    assert result == expected


def test_interface_method_id_default_args_view(get_contract, make_input_bundle):
    iface_code = """
@view
@external
def get_amount(token: address, receiver: address = ...) -> uint256:
    ...
    """
    input_bundle = make_input_bundle({"ifoo.vyi": iface_code})

    code = """
import ifoo as IFoo

@external
def get_method_id() -> bytes4:
    return IFoo.get_amount.method_id
    """
    c = get_contract(code, input_bundle=input_bundle)
    result = c.get_method_id()
    expected = method_id("get_amount(address,address)")
    assert result == expected
