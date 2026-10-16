import pytest

from vyper.compiler import compile_code
from vyper.exceptions import FunctionDeclarationException, NonPayableViolation


@pytest.mark.parametrize(
    "source",
    [
        """
@payable
@external
def foo():
    pass
    """,
        """
@payable()
@external
def foo():
    pass
    """,
        """
@external
@payable
def __default__():
    pass
    """,
        """
@deploy
@payable
def __init__():
    pass
    """,
        """
@payable
def foo():
    pass
    """,
        """
interface PiggyBank:
    def deposit(): payable
    """,
    ],
)
def test_payable_removed(source):
    with pytest.raises(FunctionDeclarationException, match="`payable` has been removed"):
        compile_code(source)


def test_payable_removed_vyi(make_input_bundle):
    ifoo = """
@payable
@external
def deposit():
    ...
    """
    code = """
import ifoo
    """
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    with pytest.raises(FunctionDeclarationException, match="`payable` has been removed"):
        compile_code(code, input_bundle=input_bundle)


def test_send_value_to_interface_function():
    code = """
interface PiggyBank:
    def deposit(): nonpayable

piggy: PiggyBank

@external
def foo():
    extcall self.piggy.deposit(value=self.balance)
    """
    compile_code(code)


@pytest.mark.parametrize("mutability", ["@view", "@pure"])
def test_msg_value_in_constant_function(mutability):
    code = f"""
@external
{mutability}
def foo() -> uint256:
    return msg.value
    """
    with pytest.raises(NonPayableViolation):
        compile_code(code)


def _abi_mutabilities(code, **kwargs):
    abi = compile_code(code, output_formats=["abi"], **kwargs)["abi"]
    return {item.get("name", item["type"]): item["stateMutability"] for item in abi}


def test_abi_payable_inference():
    code = """
@deploy
def __init__():
    pass

@external
def reads_value() -> uint256:
    return msg.value

@external
def reads_value_nested(x: uint256) -> uint256:
    if x > 0:
        return msg.value
    return 0

@external
def reads_value_via_internal() -> uint256:
    return self._value()

@external
def reads_value_via_nested_internal() -> uint256:
    return self._value_wrapper()

@external
def no_value() -> uint256:
    return 1

@external
def calls_non_value_internal() -> uint256:
    return self._no_value()

@external
@view
def view_fn() -> uint256:
    return 1

@external
@pure
def pure_fn() -> uint256:
    return 1

@internal
def _value() -> uint256:
    return msg.value

@internal
def _value_wrapper() -> uint256:
    return self._value()

@internal
def _no_value() -> uint256:
    return 1
    """
    assert _abi_mutabilities(code) == {
        "constructor": "nonpayable",
        "reads_value": "payable",
        "reads_value_nested": "payable",
        "reads_value_via_internal": "payable",
        "reads_value_via_nested_internal": "payable",
        "no_value": "nonpayable",
        "calls_non_value_internal": "nonpayable",
        "view_fn": "view",
        "pure_fn": "pure",
    }


def test_abi_payable_inference_ctor_and_fallback():
    code = """
x: uint256

@deploy
def __init__():
    self.x = msg.value

@external
def __default__():
    self.x = msg.value
    """
    assert _abi_mutabilities(code) == {"constructor": "payable", "fallback": "payable"}

    code = """
@deploy
def __init__():
    pass

@external
def __default__():
    pass
    """
    assert _abi_mutabilities(code) == {"constructor": "nonpayable", "fallback": "nonpayable"}


def test_abi_payable_inference_across_modules(make_input_bundle):
    lib = """
@internal
def get_value() -> uint256:
    return msg.value

@external
def lib_reads_value() -> uint256:
    return msg.value
    """
    code = """
import lib

exports: lib.lib_reads_value

@external
def foo() -> uint256:
    return lib.get_value()
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    assert _abi_mutabilities(code, input_bundle=input_bundle) == {
        "foo": "payable",
        "lib_reads_value": "payable",
    }


accepts_value_code = [
    """
@external
def foo() -> bool:
    return True
    """,
    """
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True

@external
def baz() -> bool:
    return True
    """,
    """
@external
@view
def foo() -> bool:
    return True
    """,
    """
@external
@pure
def foo() -> bool:
    return True
    """,
    """
@external
def foo(x: uint256 = 1) -> bool:
    return True
    """,
    """
@external
def __default__():
    a: int128 = 1

@external
def foo() -> bool:
    return True
    """,
]


@pytest.mark.parametrize("code", accepts_value_code)
def test_functions_accept_value(env, get_contract, code):
    c = get_contract(code)
    env.set_balance(env.deployer, 2 * 10**18)
    assert c.foo(value=10**18) is True
    assert c.foo(value=0) is True
    assert env.get_balance(c.address) == 10**18


def test_msg_value(env, get_contract):
    code = """
@external
def foo() -> uint256:
    return msg.value

@external
def bar() -> uint256:
    return self._value()

@internal
def _value() -> uint256:
    return msg.value
    """
    c = get_contract(code)
    env.set_balance(env.deployer, 10**18)
    assert c.foo(value=123) == 123
    assert c.bar(value=456) == 456
    assert c.foo() == 0


def test_constructor_accepts_value(env, get_contract):
    code = """
@deploy
def __init__():
    pass
    """
    env.set_balance(env.deployer, 10**18)
    c = get_contract(code, value=10**18)
    assert env.get_balance(c.address) == 10**18


def test_default_func_accepts_value(get_contract, env):
    code = """
@external
def foo() -> bool:
    return True

@external
def __default__():
    pass
    """
    c = get_contract(code)
    env.set_balance(env.deployer, 1000)
    data = bytes([1, 2, 3, 4])
    for i in range(5):
        calldata = "0x" + data[:i].hex()
        env.message_call(c.address, value=100, data=calldata)
    env.message_call(c.address, value=100, data="0x12345678")
    assert env.get_balance(c.address) == 600
