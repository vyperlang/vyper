import copy

import pytest
from eth.codecs import abi

from tests.evm_backends.abi_contract import ABIContractFactory
from tests.utils import json_input
from vyper.compiler import compile_code
from vyper.evm.opcodes import version_check
from vyper.exceptions import FunctionDeclarationException, StructureException
from vyper.utils import keccak256, method_id


def test_raw_return(get_contract, tx_failed):
    test_bytes = """
@external
@raw_return
def foo(x: Bytes[100]) -> Bytes[100]:
    return x
    """

    c = get_contract(test_bytes)
    moo_result = c.foo(abi.encode("(bytes)", (b"cow",)))
    assert moo_result == b"cow"


def test_proxy_raw_return(env, get_contract):
    impl1 = """
@external
def foo() -> String[32]:
    return "Hello"
    """

    impl2 = """
@external
def foo() -> Bytes[32]:
    return b"Goodbye"
    """

    impl3 = """
@external
def foo() -> DynArray[uint256, 2]:
    #return [1, 2]
    a: DynArray[uint256, 2] = [1, 2]
    return a
    """

    proxy = """
target: address

@external
def set_implementation(target: address):
    self.target = target

@external
@raw_return
def foo() -> Bytes[128]:
    data: Bytes[128] = raw_call(
        self.target,
        msg.data,
        is_delegate_call=True,
        max_outsize=128
    )
    return data
    """

    impl_c1 = get_contract(impl1)
    impl_c2 = get_contract(impl2)
    impl_c3 = get_contract(impl3)

    proxy_c = get_contract(proxy)

    assert impl_c1.foo() == "Hello"
    proxy_c.set_implementation(impl_c1.address)
    assert proxy_c.foo() == b"Hello"

    assert impl_c2.foo() == b"Goodbye"
    proxy_c.set_implementation(impl_c2.address)
    assert proxy_c.foo() == b"Goodbye"

    assert impl_c3.foo() == [1, 2]
    proxy_c.set_implementation(impl_c3.address)
    # need low-level call otherwise we fail due to bytes decoding
    # because ABIBytes is represented as bytes in ABI
    res = env.message_call(proxy_c.address, data=method_id("foo()"))
    assert abi.decode("(uint256[])", res) == ([1, 2],)


def test_raw_return_zero_bytes(get_contract, env, tx_failed):
    code = """
@raw_return
@external
def test() -> Bytes[1]:
    return b''

interface Self:
    def test() -> Bytes[1]: nonpayable

@external
def self_call_with_decode() -> Bytes[1]:
    return extcall Self(self).test()

@external
def self_call_no_decode() -> Bytes[1]:
    return raw_call(self, method_id("test()"), max_outsize=1)

@external
@raw_return
def self_call_no_decode2() -> Bytes[1]:
    return raw_call(self, method_id("test()"), max_outsize=1)
    """
    c = get_contract(code)
    res = env.message_call(c.address, data=method_id("test()"))
    assert res == b""

    with tx_failed():
        _ = c.self_call_with_decode()

    res = c.self_call_no_decode()
    assert res == b""

    res = env.message_call(c.address, data=method_id("self_call_no_decode2()"))
    assert res == b""


fail_list = [
    (
        # can't put @raw_return on internal functions
        """
@raw_return
def test() -> Bytes[32]:
    return b''
""",
        StructureException,
    ),
    (
        # can't put @raw_return twice
        """
@raw_return
@raw_return
@external
def test() -> Bytes[32]:
    return b''
""",
        StructureException,
    ),
    (
        """
# can't put @raw_return on ctor
@raw_return
@deploy
def __init__():
    pass
        """,
        StructureException,
    ),
    (
        # can't return non Bytes type
        """
@raw_return
@external
def test() -> uint256:
    return 666
        """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_interfaces_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


def test_raw_return_not_allowed_in_interface(make_input_bundle):
    # interface with @raw_return decorator should fail
    iface = """
@external
@raw_return
def foo() -> Bytes[32]:
    ...
    """
    # doesn't implement @raw_return decorator
    main = """
import iface

implements: iface

@external
def foo() -> Bytes[32]:
    return b''
    """
    input_bundle = make_input_bundle({"iface.vyi": iface})

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value._message == "`@raw_return` not allowed in interfaces"


# test raw_return from storage, transient, constant and immutable
# calldata Bytes[..] need clamp and thus are internally coppied to memory
@pytest.mark.parametrize("to_ret", ["self.s", "self.t", "c", "i"])
def test_raw_return_from_location(env, get_contract, to_ret):
    has_transient = version_check(begin="cancun")
    if to_ret == "self.t" and not has_transient:
        # no transient available before cancun
        pytest.skip()

    t_decl = "t: transient(Bytes[32])" if has_transient else ""
    t_assign = "self.t = b'cow'" if has_transient else ""
    test_bytes = f"""
s: Bytes[32]
{t_decl}
c: constant(Bytes[32]) = b'cow'
i: immutable(Bytes[32])

@deploy
def __init__():
    self.s = b'cow'
    i = b'cow'

@external
@raw_return
def get() -> Bytes[100]:
    {t_assign}
    return {to_ret}
    """

    c = get_contract(test_bytes)
    res = env.message_call(c.address, data=method_id("get()"))
    assert res == b"cow"


def test_raw_return_fallback(env, get_contract, tx_failed):
    ret = b"a" * 32
    test_bytes = f"""
@external
@raw_return
def __default__() -> Bytes[32]:
    return {ret}
    """

    c = get_contract(test_bytes)
    res = env.message_call(c.address, data=method_id("get()"))
    assert res == ret


def _cast(impl_contract, proxy_address):
    factory = ABIContractFactory.from_abi_dict(
        impl_contract.abi, name=impl_contract._name, bytecode=impl_contract.bytecode
    )

    # Create a new contract instance at the proxy address
    return factory.at(impl_contract.env, proxy_address)


def test_proxy_upgrade_with_access_control(env, get_contract, tx_failed):
    impl_template = """
counter: uint256
admin: address
implementation: address

@deploy
def __init__():
    self.admin = empty(address)
    self.counter = 0

@external
def increment():
    self.counter += {increment_value}

@external
@view
def get_counter() -> uint256:
    return self.counter

@external
@view
def get_admin() -> address:
    return self.admin

@external
def set_admin(new_admin: address):
    assert msg.sender == self.admin, "Only admin"
    self.admin = new_admin

@external
@view
def get_implementation() -> address:
    return self.implementation

@external
def upgrade_to(new_implementation: address):
    assert msg.sender == self.admin, "Only admin can upgrade"
    self.implementation = new_implementation
    """

    # Implementation V1 - increments by 1
    impl_v1 = impl_template.format(increment_value=1)

    # Implementation V2 - increments by 2
    impl_v2 = impl_template.format(increment_value=2)

    impl_v3 = impl_template.format(increment_value=4)

    proxy_code = """
implementation: address
admin: address
RESPONSE_SZ: constant(uint256) = 2**12

@deploy
def __init__(implementation_: address):
    self.implementation = implementation_
    self.admin = msg.sender

@external
@payable
@raw_return
def __default__() -> Bytes[RESPONSE_SZ]:
    return raw_call(
        self.implementation,
        msg.data,
        max_outsize=RESPONSE_SZ,
        is_delegate_call=True,
    )
    """

    implementation_slot = keccak256(b"proxy.implementation")
    admin_slot = keccak256(b"proxy.admin")

    proxy_override = {
        "implementation": {
            "slot": int.from_bytes(implementation_slot, byteorder="big"),
            "type": "address",
            "n_slots": 1,
        },
        "admin": {
            "slot": int.from_bytes(admin_slot, byteorder="big"),
            "type": "address",
            "n_slots": 1,
        },
    }
    impl_override = copy.deepcopy(proxy_override)
    impl_override["counter"] = {"slot": 1, "type": "uint256", "n_slots": 1}

    impl_v1_c = get_contract(impl_v1, storage_layout_override=json_input(impl_override))

    proxy_c = get_contract(
        proxy_code, impl_v1_c.address, storage_layout_override=json_input(proxy_override)
    )

    # Cast proxy to implementation V1 interface
    proxy_as_impl = _cast(impl_v1_c, proxy_c.address)

    # Test initial state
    assert proxy_as_impl.get_counter() == 0
    assert proxy_as_impl.get_admin() == env.deployer
    assert proxy_as_impl.get_implementation() == impl_v1_c.address
    assert proxy_as_impl.get_admin() == env.deployer

    proxy_as_impl.increment()
    assert proxy_as_impl.get_counter() == 1

    proxy_as_impl.increment()
    assert proxy_as_impl.get_counter() == 2

    assert proxy_as_impl.get_admin() != env.accounts[1]
    with tx_failed():
        proxy_as_impl.set_admin(env.accounts[1], sender=env.accounts[1])

    # Change admin successfully
    assert proxy_as_impl.get_admin() == env.deployer
    admin1 = env.accounts[1]
    proxy_as_impl.set_admin(admin1)
    assert proxy_as_impl.get_admin() == admin1

    # Deploy implementation V2
    impl_v2_c = get_contract(impl_v2, storage_layout_override=json_input(impl_override))

    # Test upgrade access control
    assert proxy_as_impl.get_admin() != env.accounts[2]
    with tx_failed():
        proxy_as_impl.upgrade_to(impl_v2_c.address, sender=env.accounts[2])

    # Upgrade successfully as proxy admin
    proxy_as_impl.upgrade_to(impl_v2_c.address, sender=admin1)

    # Verify state is preserved after upgrade
    assert proxy_as_impl.get_counter() == 2
    assert proxy_as_impl.get_admin() == admin1

    # Test new functionality - V2 increments by 2 instead of 1
    proxy_as_impl.increment()
    assert proxy_as_impl.get_counter() == 4  # 2 + 2

    proxy_as_impl.increment()
    assert proxy_as_impl.get_counter() == 6  # 4 + 2

    # Test proxy admin change
    admin2 = env.accounts[2]
    with tx_failed():
        proxy_as_impl.set_admin(admin2, sender=admin2)

    proxy_as_impl.set_admin(admin2, sender=admin1)
    assert proxy_as_impl.get_admin() == admin2

    with tx_failed():
        proxy_as_impl.upgrade_to(impl_v1_c.address, sender=admin1)

    impl_v3_c = get_contract(impl_v3, storage_layout_override=json_input(impl_override))

    proxy_as_impl.upgrade_to(impl_v3_c.address, sender=admin2)
    proxy_as_impl.increment()
    assert proxy_as_impl.get_counter() == 10  # 6 + 4
