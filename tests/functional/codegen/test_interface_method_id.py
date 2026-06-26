from vyper.utils import method_id


def test_method_id_of_basic(get_contract):
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def get_method_id() -> bytes4:
    return method_id_of(Foo.transfer)
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("transfer(address,uint256)")
    assert result == expected


def test_method_id_of_view_function(get_contract):
    code = """
interface Foo:
    def balanceOf(owner: address) -> uint256: view

@external
def get_method_id() -> bytes4:
    return method_id_of(Foo.balanceOf)
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("balanceOf(address)")
    assert result == expected


def test_method_id_of_no_args(get_contract):
    code = """
interface Foo:
    def totalSupply() -> uint256: view

@external
def get_method_id() -> bytes4:
    return method_id_of(Foo.totalSupply)
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("totalSupply()")
    assert result == expected


def test_method_id_of_in_raw_call(get_contract):
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
        concat(method_id_of(Doubler.double), convert(x, bytes32)),
        max_outsize=32
    )
    return convert(convert(response, bytes32), uint256)
    """
    callee = get_contract(called_code)
    caller = get_contract(caller_code)
    assert caller.call_double(callee.address, 5) == 10


def test_method_id_of_assign_to_variable(get_contract):
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def get_method_id() -> bytes4:
    m: bytes4 = method_id_of(Foo.transfer)
    return m
    """
    c = get_contract(code)
    result = c.get_method_id()
    expected = method_id("transfer(address,uint256)")
    assert result == expected


def test_method_id_of_compare(get_contract):
    code = """
interface Foo:
    def transfer(to: address, amount: uint256): nonpayable

@external
def check() -> bool:
    return method_id_of(Foo.transfer) == method_id('transfer(address,uint256)', output_type=bytes4)
    """
    c = get_contract(code)
    assert c.check() is True


def test_method_id_of_default_args(get_contract, make_input_bundle):
    iface_code = """
@external
def take(auction_id: uint256, max_take_amount: uint256 = ...) -> uint256:
    ...
    """
    input_bundle = make_input_bundle({"ifoo.vyi": iface_code})

    code = """
import ifoo as IFoo

@external
def get_full() -> bytes4:
    return method_id_of(IFoo.take, n_optional_args=1)

@external
def get_minimal() -> bytes4:
    return method_id_of(IFoo.take)

@external
def get_default() -> bytes4:
    return method_id_of(IFoo.take, n_optional_args=0)
    """
    c = get_contract(code, input_bundle=input_bundle)
    # full signature (all args, 1 optional included)
    assert c.get_full() == method_id("take(uint256,uint256)")
    # minimal signature (positional only, default n_optional_args=0)
    assert c.get_minimal() == method_id("take(uint256)")
    # explicit n_optional_args=0, same as default
    assert c.get_default() == method_id("take(uint256)")


def test_method_id_of_default_args_view(get_contract, make_input_bundle):
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
    return method_id_of(IFoo.get_amount)
    """
    c = get_contract(code, input_bundle=input_bundle)
    result = c.get_method_id()
    # default n_optional_args=0, so only positional args
    expected = method_id("get_amount(address)")
    assert result == expected
