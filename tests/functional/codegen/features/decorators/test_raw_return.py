import pytest
from eth.codecs import abi

from vyper.compiler import compile_code
from vyper.evm.opcodes import version_check
from vyper.exceptions import FunctionDeclarationException, StructureException
from vyper.utils import method_id


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
