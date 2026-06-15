from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings, VenomOptimizationFlags
from vyper.utils import method_id


def _venom_settings(*, disable_inlining=False):
    settings = Settings(experimental_codegen=True)
    if disable_inlining:
        settings.venom_flags = VenomOptimizationFlags(disable_inlining=True)
    return settings


def _compile_venom(code, output_formats, *, settings=None):
    return compile_code(code, output_formats=output_formats, settings=settings or _venom_settings())


def _deploy_venom(env, code, *, settings=None):
    out = _compile_venom(code, ["bytecode"], settings=settings)
    return env.deploy([], bytes.fromhex(out["bytecode"].removeprefix("0x")))


def _deploy_venom_with_ctor_data(env, code, ctor_data, *, settings=None):
    out = _compile_venom(code, ["bytecode"], settings=settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x")) + ctor_data
    return env.deploy([], initcode)


def _call(env, contract, signature, args_schema=None, args=None):
    calldata = method_id(signature)
    if args_schema is not None:
        calldata += abi_encode(args_schema, args)
    return env.message_call(contract.address, data=calldata)


def test_inf_dynarray_local_from_literal(env):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "foo()")) == ([1, 2, 3],)


def test_inf_dynarray_local_from_bounded(env):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    bounded: DynArray[uint256, 5] = [11, 22, 33]
    x: DynArray[uint256, INF] = bounded
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "foo()")) == ([11, 22, 33],)


def test_inf_dynarray_external_param_roundtrip(env):
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([4, 5, 6, 7],))
    assert abi_decode("(uint256[])", ret) == ([4, 5, 6, 7],)


def test_empty_inf_dynarray_external_param_roundtrip(env):
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([],))
    assert abi_decode("(uint256[])", ret) == ([],)


def test_large_inf_dynarray_external_param_roundtrip(env):
    payload = [i * 17 for i in range(2001)]
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", (payload,))
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_reassignment_larger_and_smaller(env):
    code = """
@external
def grow() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1]
    x = [1, 2, 3, 4, 5]
    return x

@external
def shrink() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3, 4, 5]
    x = [9]
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "grow()")) == ([1, 2, 3, 4, 5],)
    assert abi_decode("(uint256[])", _call(env, c, "shrink()")) == ([9],)


def test_inf_dynarray_if_reassignment(env):
    code = """
@external
def pick(flag: bool) -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2]
    if flag:
        x = [10, 20, 30, 40]
    else:
        x = [7]
    return x
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "pick(bool)", "bool", True)
    assert abi_decode("(uint256[])", ret) == ([10, 20, 30, 40],)
    ret = _call(env, c, "pick(bool)", "bool", False)
    assert abi_decode("(uint256[])", ret) == ([7],)


def test_inf_dynarray_internal_arg_return_roundtrip(env):
    code = """
@internal
def _echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x

@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return self._echo(x)
    """

    c = _deploy_venom(env, code)
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([3, 1, 4, 1, 5],))
    assert abi_decode("(uint256[])", ret) == ([3, 1, 4, 1, 5],)


def test_inf_dynarray_internal_arg_return_no_inline(env):
    code = """
@internal
def _echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x

@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return self._echo(x)
    """

    c = _deploy_venom(env, code, settings=_venom_settings(disable_inlining=True))
    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([8, 6, 7, 5, 3, 0, 9],))
    assert abi_decode("(uint256[])", ret) == ([8, 6, 7, 5, 3, 0, 9],)


def test_inf_dynarray_external_kwarg_default_and_provided(env):
    code = """
@external
def echo(x: DynArray[uint256, INF] = [12, 34]) -> DynArray[uint256, INF]:
    return x
    """

    c = _deploy_venom(env, code)
    assert abi_decode("(uint256[])", _call(env, c, "echo()")) == ([12, 34],)

    ret = _call(env, c, "echo(uint256[])", "(uint256[])", ([56, 78, 90],))
    assert abi_decode("(uint256[])", ret) == ([56, 78, 90],)


def test_inf_dynarray_constructor_param(env):
    code = """
stored_len: immutable(uint256)
stored_item: immutable(uint256)

@deploy
def __init__(x: DynArray[uint256, INF]):
    stored_len = len(x)
    stored_item = x[3]

@external
def get() -> (uint256, uint256):
    return stored_len, stored_item
    """

    ctor_data = abi_encode("(uint256[])", ([11, 22, 33, 44, 55],))
    c = _deploy_venom_with_ctor_data(env, code, ctor_data)
    assert abi_decode("(uint256,uint256)", _call(env, c, "get()")) == (5, 44)


def test_inf_dynarray_staticcall_return_roundtrip(env):
    target_code = """
@external
@view
def data() -> DynArray[uint256, INF]:
    return [10, 20, 30]
    """

    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data()
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(env, caller, "get(address)", "address", target.address)
    assert abi_decode("(uint256[])", ret) == ([10, 20, 30],)


def test_large_inf_dynarray_staticcall_inf_arg_roundtrip(env):
    payload = [i * 29 for i in range(2001)]
    target_code = """
@external
@view
def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]: view

@external
def get(addr: address, x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data(x)
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env, caller, "get(address,uint256[])", "(address,uint256[])", (target.address, payload)
    )
    assert abi_decode("(uint256[])", ret) == (payload,)


def test_inf_dynarray_extcall_inf_arg_roundtrip(env):
    target_code = """
@external
def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]: nonpayable

@external
def get(addr: address, x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return extcall Source(addr).data(x)
    """

    target = _deploy_venom(env, target_code)
    caller = _deploy_venom(env, caller_code)
    ret = _call(
        env, caller, "get(address,uint256[])", "(address,uint256[])", (target.address, [9, 8, 7])
    )
    assert abi_decode("(uint256[])", ret) == ([9, 8, 7],)
