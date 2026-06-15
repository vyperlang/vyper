from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.utils import method_id


def _deploy_venom(env, code):
    out = compile_code(
        code,
        output_formats=["bytecode"],
        settings=Settings(experimental_codegen=True),
    )
    return env.deploy([], bytes.fromhex(out["bytecode"].removeprefix("0x")))


def _call(env, contract, signature, args_schema=None, args=None):
    calldata = method_id(signature)
    if args_schema is not None:
        calldata += abi_encode(args_schema, args)
    return env.message_call(contract.address, data=calldata)


def test_inf_bytes_local_from_bounded(env):
    code = """
@external
def foo() -> Bytes[5]:
    x: Bytes[INF] = b"hello"
    return slice(x, 0, 5)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo()")) == (b"hello",)


def test_inf_string_local_from_bounded(env):
    code = """
@external
def foo() -> String[5]:
    x: String[INF] = "hello"
    return slice(x, 0, 5)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(string)", _call(env, c, "foo()")) == ("hello",)


def test_inf_bytes_and_string_locals_from_bounded_params(env):
    code = """
@external
def foo(a: Bytes[5], b: String[5]) -> (Bytes[5], String[5]):
    x: Bytes[INF] = a
    y: String[INF] = b
    return slice(x, 0, 5), slice(y, 0, 5)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "foo(bytes,string)", "(bytes,string)", (b"hello", "world"))
    assert abi_decode("(bytes,string)", ret) == (b"hello", "world")


def test_empty_inf_bytes_and_string_locals(env):
    code = """
@external
def foo() -> (uint256, uint256):
    x: Bytes[INF] = b""
    y: String[INF] = ""
    return len(x), len(y)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256,uint256)", _call(env, c, "foo()")) == (0, 0)


def test_inf_bytes_local_reassignment_larger_and_smaller(env):
    code = """
@external
def grow() -> Bytes[6]:
    x: Bytes[INF] = b"cat"
    x = b"kitten"
    return slice(x, 0, 6)

@external
def shrink() -> Bytes[3]:
    x: Bytes[INF] = b"kitten"
    x = b"cat"
    return slice(x, 0, 3)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "grow()")) == (b"kitten",)
    assert abi_decode("(bytes)", _call(env, c, "shrink()")) == (b"cat",)


def test_inf_bytes_local_reassignment_in_if(env):
    code = """
@external
def foo(flag: bool) -> Bytes[3]:
    x: Bytes[INF] = b"abc"
    if flag:
        x = b"defg"
    return slice(x, 0, 3)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", False)) == (b"abc",)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", True)) == (b"def",)


def test_inf_bytes_local_reassignment_in_loop(env):
    code = """
@external
def foo(flag: bool) -> Bytes[3]:
    x: Bytes[INF] = b"one"
    for i: uint256 in range(2):
        if flag and i == 1:
            x = b"two"
    return slice(x, 0, 3)
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", False)) == (b"one",)
    assert abi_decode("(bytes)", _call(env, c, "foo(bool)", "bool", True)) == (b"two",)
