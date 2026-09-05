import pytest

from tests.evm_backends.abi import abi_decode, abi_encode
from vyper.compiler import compile_code
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _deploy_with_ctor_data(env, code, ctor_data, settings):
    out = compile_code(code, output_formats=["abi", "bytecode"], settings=settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x")) + ctor_data
    return env.deploy(out["abi"], initcode)


def _deploy_raw_returner(env, payload):
    assert len(payload) < 256
    runtime = bytes(
        [0x60, len(payload), 0x60, 12, 0x60, 0, 0x39, 0x60, len(payload), 0x60, 0, 0xF3]
    )
    runtime += payload
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def test_inf_dynarray_local_from_literal(get_contract):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    return x
    """

    c = get_contract(code)
    assert c.foo() == [1, 2, 3]


def test_inf_dynarray_local_from_bounded(get_contract):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    bounded: DynArray[uint256, 5] = [11, 22, 33]
    x: DynArray[uint256, INF] = bounded
    return x
    """

    c = get_contract(code)
    assert c.foo() == [11, 22, 33]


def test_empty_inf_dynarray_builtin(get_contract):
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    return empty(DynArray[uint256, INF])
    """

    c = get_contract(code)
    assert c.foo() == []


def test_empty_inf_dynarray_dynamic_tuple_builtin(get_contract):
    code = """
@external
def value() -> (uint256, DynArray[uint256, INF]):
    return empty((uint256, DynArray[uint256, INF]))
    """

    c = get_contract(code)
    assert c.value() == (0, [])


def test_inf_dynarray_composite_static_elements(get_contract):
    code = """
struct S:
    a: uint256
    b: bytes32

@external
def static_arrays(x: DynArray[uint256[2], INF]) -> (uint256, DynArray[uint256[2], INF]):
    y: DynArray[uint256[2], INF] = x
    y.append([5, 6])
    total: uint256 = 0
    for item: uint256[2] in y:
        total += item[0] + item[1]
    return total, y

@external
def structs(x: DynArray[S, INF]) -> (uint256, DynArray[S, INF]):
    y: DynArray[S, INF] = x
    y.append(S(a=5, b=0x0505050505050505050505050505050505050505050505050505050505050505))
    total: uint256 = 0
    for item: S in y:
        total += item.a
    return total, y
    """

    c = get_contract(code)
    assert c.static_arrays([(1, 2), (3, 4)]) == (21, [[1, 2], [3, 4], [5, 6]])

    first = (1, bytes.fromhex("01" * 32))
    second = (3, bytes.fromhex("03" * 32))
    appended = (5, bytes.fromhex("05" * 32))
    assert c.structs([first, second]) == (9, [first, second, appended])


def test_inf_dynarray_external_param_roundtrip(get_contract):
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo([4, 5, 6, 7]) == [4, 5, 6, 7]


def test_empty_inf_dynarray_external_param_roundtrip(get_contract):
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo([]) == []


def test_large_inf_dynarray_external_param_roundtrip(get_contract):
    payload = [i * 17 for i in range(2001)]
    code = """
@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo(payload) == payload


def test_inf_dynarray_reassignment_larger_and_smaller(get_contract):
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

    c = get_contract(code)
    assert c.grow() == [1, 2, 3, 4, 5]
    assert c.shrink() == [9]


def test_inf_dynarray_if_reassignment(get_contract):
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

    c = get_contract(code)
    assert c.pick(True) == [10, 20, 30, 40]
    assert c.pick(False) == [7]


def test_inf_dynarray_append_reallocates(get_contract):
    code = """
@external
def grow(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    y: DynArray[uint256, INF] = x
    y.append(99)
    y.append(123)
    return y
    """

    c = get_contract(code)
    assert c.grow([1, 2, 3]) == [1, 2, 3, 99, 123]


def test_inf_dynarray_append_loop(get_contract):
    code = """
@external
def build() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = []
    for i: uint256 in range(64):
        x.append(i * i + 7)
    return x
    """

    c = get_contract(code)
    assert c.build() == [i * i + 7 for i in range(64)]


def test_inf_dynarray_append_loop_full_contents(get_contract):
    code = """
@external
def build(n: uint256) -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = []
    for i: uint256 in range(n, bound=100):
        x.append(i * 3 + 1)
    return x
    """

    c = get_contract(code)
    for n in [0, 1, 2, 3, 5, 8, 13, 20]:
        assert c.build(n) == [i * 3 + 1 for i in range(n)]


def test_inf_dynarray_append_after_assignment_and_calldata(get_contract):
    code = """
@external
def from_literal() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    x.append(4)
    x.append(5)
    return x

@external
def from_calldata(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    y: DynArray[uint256, INF] = x
    y.append(7)
    y.append(8)
    return y
    """

    c = get_contract(code)
    assert c.from_literal() == [1, 2, 3, 4, 5]
    assert c.from_calldata([4, 5, 6]) == [4, 5, 6, 7, 8]


def test_inf_dynarray_append_reassign_append(get_contract):
    code = """
@external
def check() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1]
    x.append(2)
    x.append(3)
    x = [10, 20]
    x.append(30)
    return x
    """

    c = get_contract(code)
    assert c.check() == [10, 20, 30]


def test_inf_dynarray_append_after_kwarg_default(get_contract):
    code = """
@external
def build(x: DynArray[uint256, INF] = [12, 34]) -> DynArray[uint256, INF]:
    y: DynArray[uint256, INF] = x
    y.append(56)
    return y
    """

    c = get_contract(code)
    assert c.build() == [12, 34, 56]
    assert c.build([1]) == [1, 56]


def test_inf_dynarray_internal_arg_append_does_not_mutate_caller(
    get_contract, no_inlining_settings
):
    code = """
@internal
def _extend(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    x.append(4)
    x.append(5)
    return x

@external
def check() -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    x: DynArray[uint256, INF] = [1, 2, 3]
    y: DynArray[uint256, INF] = self._extend(x)
    return x, y
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.check() == ([1, 2, 3], [1, 2, 3, 4, 5])


def test_inf_dynarray_two_locals_alternating_append(get_contract):
    code = """
@external
def build(n: uint256) -> (DynArray[uint256, INF], DynArray[uint256, INF]):
    a: DynArray[uint256, INF] = []
    b: DynArray[uint256, INF] = []
    for i: uint256 in range(n, bound=50):
        a.append(i)
        b.append(i * 100)
    return a, b
    """

    c = get_contract(code)
    for n in [0, 1, 7, 20]:
        assert c.build(n) == (list(range(n)), [i * 100 for i in range(n)])


def test_inf_dynarray_pop_then_append_full_contents(get_contract):
    code = """
@external
def check() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = []
    for i: uint256 in range(6):
        x.append(i)
    y: uint256 = x.pop()
    x.append(y + 100)
    x.append(200)
    return x
    """

    c = get_contract(code)
    assert c.check() == [0, 1, 2, 3, 4, 105, 200]


def test_inf_dynarray_indexed_store(get_contract, tx_failed):
    code = """
@external
def set(i: uint256, val: uint256) -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [10, 20, 30]
    x[i] = val
    return x
    """

    c = get_contract(code)
    assert c.set(1, 99) == [10, 99, 30]

    # indexed store into an INF dynarray retains the runtime out-of-bounds guard
    with tx_failed():
        c.set(3, 99)


def test_inf_dynarray_internal_call_freezes_arg_before_later_mutation(get_contract):
    code = """
@internal
def _len(a: DynArray[uint256, INF], popped: uint256) -> uint256:
    return len(a) * 10 + popped

@external
def check() -> (uint256, DynArray[uint256, INF]):
    x: DynArray[uint256, INF] = [1, 2, 3]
    r: uint256 = self._len(x, x.pop())
    return r, x
    """

    c = get_contract(code)
    assert c.check() == (33, [1, 2])


def test_inf_dynarray_external_call_freezes_arg_before_later_mutation(get_contract):
    target_code = """
@external
@view
def length(a: DynArray[uint256, INF], popped: uint256) -> uint256:
    return len(a) * 10 + popped
    """
    caller_code = """
interface Target:
    def length(a: DynArray[uint256, INF], popped: uint256) -> uint256: view

@external
def check(addr: address) -> (uint256, DynArray[uint256, INF]):
    x: DynArray[uint256, INF] = [1, 2, 3]
    r: uint256 = staticcall Target(addr).length(x, x.pop())
    return r, x
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.check(target.address) == (33, [1, 2])


def test_inf_dynarray_external_call_freezes_bounded_arg_in_runtime_encoding(get_contract):
    target_code = """
@external
@view
def lengths(a: DynArray[uint256, 3], b: DynArray[uint256, INF], popped: uint256) -> uint256:
    return len(a) * 100 + len(b) * 10 + popped
    """
    caller_code = """
interface Target:
    def lengths(
        a: DynArray[uint256, 3],
        b: DynArray[uint256, INF],
        popped: uint256
    ) -> uint256: view

@external
def check(addr: address) -> (uint256, DynArray[uint256, 3], DynArray[uint256, INF]):
    a: DynArray[uint256, 3] = [4, 5, 6]
    b: DynArray[uint256, INF] = [1, 2, 3]
    r: uint256 = staticcall Target(addr).lengths(a, b, a.pop())
    return r, a, b
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.check(target.address) == (336, [4, 5], [1, 2, 3])


def test_inf_dynarray_internal_call_freezes_bounded_arg_in_runtime_encoding(
    get_contract, no_inlining_settings
):
    code = """
@internal
def _lengths(
    a: DynArray[uint256, 3],
    b: DynArray[uint256, INF],
    popped: uint256
) -> uint256:
    return len(a) * 100 + len(b) * 10 + popped

@external
def check() -> (uint256, DynArray[uint256, 3], DynArray[uint256, INF]):
    a: DynArray[uint256, 3] = [4, 5, 6]
    b: DynArray[uint256, INF] = [1, 2, 3]
    r: uint256 = self._lengths(a, b, a.pop())
    return r, a, b
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.check() == (336, [4, 5], [1, 2, 3])


def test_inf_dynarray_tuple_literal_return_freezes_member_before_later_mutation(get_contract):
    code = """
@external
def check() -> (DynArray[uint256, INF], uint256, DynArray[uint256, INF]):
    x: DynArray[uint256, INF] = [1, 2, 3]
    return x, x.pop(), x
    """

    c = get_contract(code)
    assert c.check() == ([1, 2, 3], 3, [1, 2])


def test_inf_dynarray_abi_encode_freezes_arg_before_later_mutation(get_contract):
    code = """
@external
def check() -> (Bytes[INF], DynArray[uint256, INF]):
    x: DynArray[uint256, INF] = [1, 2, 3]
    encoded: Bytes[INF] = abi_encode(x, x.pop())
    return encoded, x
    """

    c = get_contract(code)
    encoded, arr = c.check()
    assert abi_decode("(uint256[],uint256)", encoded) == ([1, 2, 3], 3)
    assert arr == [1, 2]


def test_inf_dynarray_abi_encode_freezes_bounded_arg_in_runtime_encoding(get_contract):
    code = """
@external
def check() -> (Bytes[INF], DynArray[uint256, 3], DynArray[uint256, INF]):
    a: DynArray[uint256, 3] = [4, 5, 6]
    b: DynArray[uint256, INF] = [1, 2, 3]
    encoded: Bytes[INF] = abi_encode(a, b, a.pop())
    return encoded, a, b
    """

    c = get_contract(code)
    encoded, bounded, unbounded = c.check()
    assert abi_decode("(uint256[],uint256[],uint256)", encoded) == ([4, 5, 6], [1, 2, 3], 6)
    assert bounded == [4, 5]
    assert unbounded == [1, 2, 3]


def test_inf_dynarray_pop_runtime(get_contract, tx_failed):
    code = """
struct S:
    a: uint256
    b: bytes32

@external
def pop_primitive() -> (uint256, DynArray[uint256, INF]):
    x: DynArray[uint256, INF] = [1, 2, 3]
    y: uint256 = x.pop()
    return y, x

@external
def pop_then_append() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    y: uint256 = x.pop()
    x.append(y + 6)
    return x

@external
def pop_array() -> (uint256[2], DynArray[uint256[2], INF]):
    x: DynArray[uint256[2], INF] = [[1, 2], [3, 4]]
    y: uint256[2] = x.pop()
    return y, x

@external
def pop_struct() -> (S, DynArray[S, INF]):
    x: DynArray[S, INF] = [
        S(a=1, b=0x0101010101010101010101010101010101010101010101010101010101010101),
        S(a=2, b=0x0202020202020202020202020202020202020202020202020202020202020202),
    ]
    y: S = x.pop()
    return y, x

@external
def pop_maybe(flag: bool) -> uint256:
    x: DynArray[uint256, INF] = []
    if flag:
        x.append(1)
    return x.pop()
    """

    c = get_contract(code)
    assert c.pop_primitive() == (3, [1, 2])
    assert c.pop_then_append() == [1, 2, 9]
    assert c.pop_array() == ([3, 4], [[1, 2]])

    first = (1, bytes.fromhex("01" * 32))
    second = (2, bytes.fromhex("02" * 32))
    assert c.pop_struct() == (second, [first])

    assert c.pop_maybe(True) == 1
    with tx_failed():
        c.pop_maybe(False)


def test_inf_dynarray_for_loop(get_contract):
    code = """
@external
def total(x: DynArray[uint256, INF]) -> uint256:
    ret: uint256 = 0
    for item: uint256 in x:
        ret += item
    return ret
    """

    c = get_contract(code)
    assert c.total([5, 8, 13, 21]) == 47


def test_inf_dynarray_membership(get_contract):
    payload = [i * 11 for i in range(2001)]
    code = """
@external
def contains(x: DynArray[uint256, INF], a: uint256) -> bool:
    return a in x

@external
def missing(x: DynArray[uint256, INF], a: uint256) -> bool:
    return a not in x
    """

    c = get_contract(code)
    assert c.contains(payload, 22000) is True
    assert c.contains(payload, 22001) is False
    assert c.missing(payload, 22001) is True
    assert c.contains([], 0) is False


def test_inf_dynarray_print(get_contract):
    payload = [i * 13 for i in range(2001)]
    code = """
@external
def log_values(x: DynArray[uint256, INF]) -> (uint256, uint256, uint256):
    print(x)
    print(x, hardhat_compat=True)
    return len(x), x[0], x[2000]
    """

    c = get_contract(code)
    assert c.log_values(payload) == (len(payload), payload[0], payload[-1])


def test_inf_dynarray_internal_arg_return_roundtrip(get_contract):
    code = """
@internal
def _echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x

@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return self._echo(x)
    """

    c = get_contract(code)
    assert c.echo([3, 1, 4, 1, 5]) == [3, 1, 4, 1, 5]


def test_inf_dynarray_internal_arg_return_no_inline(get_contract, no_inlining_settings):
    code = """
@internal
def _echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x

@external
def echo(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return self._echo(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.echo([8, 6, 7, 5, 3, 0, 9]) == [8, 6, 7, 5, 3, 0, 9]


def test_inf_dynarray_internal_tuple_return_no_inline(get_contract, no_inlining_settings):
    payload = [i * 19 for i in range(2001)]
    code = """
@internal
def _pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return 17, x

@external
def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return self._pair(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload) == (17, payload)


def test_inf_dynarray_internal_tuple_unpack_no_inline(get_contract, no_inlining_settings):
    code = """
@internal
def _pair() -> (uint256, DynArray[uint256, INF]):
    return 23, [4, 5, 6]

@external
def unpack() -> (uint256, uint256, uint256):
    a: uint256 = 0
    b: DynArray[uint256, INF] = []
    a, b = self._pair()
    return a, len(b), b[2]
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.unpack() == (23, 3, 6)


def test_inf_dynarray_external_kwarg_default_and_provided(get_contract):
    code = """
@external
def echo(x: DynArray[uint256, INF] = [12, 34]) -> DynArray[uint256, INF]:
    return x
    """

    c = get_contract(code)
    assert c.echo() == [12, 34]

    assert c.echo([56, 78, 90]) == [56, 78, 90]


def test_inf_dynarray_constructor_param(get_contract):
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

    c = get_contract(code, [11, 22, 33, 44, 55])
    assert c.get() == (5, 44)


def test_inf_dynarray_constructor_param_allows_truncated_data(env, compiler_settings):
    code = """
@deploy
def __init__(x: DynArray[uint256, INF]):
    pass

@external
def ok() -> uint256:
    return 1
    """

    def word(value):
        return value.to_bytes(32, "big")

    c = _deploy_with_ctor_data(env, code, word(32) + word(2) + word(1), compiler_settings)
    assert c.ok() == 1


def test_inf_dynarray_staticcall_return_roundtrip(get_contract):
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

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address) == [10, 20, 30]


def test_inf_dynarray_staticcall_return_rejects_wrapped_length(env, get_contract, tx_failed):
    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data()
    """

    caller = get_contract(caller_code)

    def word(value):
        return value.to_bytes(32, "big")

    target = _deploy_raw_returner(env, word(32) + word(2**251))
    with tx_failed():
        caller.get(target.address)


def test_inf_dynarray_staticcall_default_return_value(env, get_contract):
    payload = [10, 20, 30]
    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address) -> DynArray[uint256, INF]:
    return staticcall Source(addr).data(default_return_value=[7, 8, 9])
    """

    caller = get_contract(caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    assert caller.get(empty_target.address) == [7, 8, 9]

    target = _deploy_raw_returner(env, abi_encode("(uint256[])", (payload,)))
    assert caller.get(target.address) == payload


def test_inf_dynarray_staticcall_default_return_value_from_inf_local(env, get_contract):
    payload = [i * 47 for i in range(2001)]
    caller_code = """
interface Source:
    def data() -> DynArray[uint256, INF]: view

@external
def get(addr: address, x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    fallback: DynArray[uint256, INF] = x
    return staticcall Source(addr).data(default_return_value=fallback)
    """

    caller = get_contract(caller_code)
    empty_target = _deploy_raw_returner(env, b"")
    assert caller.get(empty_target.address, payload) == payload


def test_inf_dynarray_staticcall_tuple_return_roundtrip(get_contract):
    payload = [i * 43 for i in range(2001)]
    target_code = """
@external
@view
def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return 41, x
    """

    caller_code = """
interface Source:
    def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]): view

@external
def get(addr: address, x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return staticcall Source(addr).pair(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == (41, payload)


def test_inf_dynarray_extcall_tuple_return_roundtrip(get_contract):
    payload = [i * 47 for i in range(2001)]
    target_code = """
@external
def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return 47, x
    """

    caller_code = """
interface Source:
    def pair(x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]): nonpayable

@external
def get(addr: address, x: DynArray[uint256, INF]) -> (uint256, DynArray[uint256, INF]):
    return extcall Source(addr).pair(x)
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == (47, payload)


def test_large_inf_dynarray_staticcall_inf_arg_roundtrip(get_contract):
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

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, payload) == payload


def test_inf_dynarray_extcall_inf_arg_roundtrip(get_contract):
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

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get(target.address, [9, 8, 7]) == [9, 8, 7]


def test_wildcard_arg_literal_roundtrip(get_contract):
    target_code = """
@external
def data(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    return x
    """

    caller_code = """
interface Source:
    def data(x: DynArray[uint256, ...]) -> DynArray[uint256, ...]: nonpayable

@external
def get_empty(addr: address) -> DynArray[uint256, 4]:
    return extcall Source(addr).data([])

@external
def get_literal(addr: address) -> DynArray[uint256, 4]:
    return extcall Source(addr).data([5, 6])
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    assert caller.get_empty(target.address) == []
    assert caller.get_literal(target.address) == [5, 6]


@pytest.mark.parametrize(
    "caller_code",
    [
        # wildcard tuple return resolved by the bounded parameter type
        """
interface Target:
    def source() -> (Bytes[...], DynArray[uint256, ...]): nonpayable
    def sink(x: (Bytes[10], DynArray[uint256, 3])): nonpayable

@external
def forward(addr: address):
    extcall Target(addr).sink(extcall Target(addr).source())
        """,
        # bounded local tuple passed to a wildcard parameter
        """
interface Target:
    def sink(x: (Bytes[10], DynArray[uint256, ...])): nonpayable

@external
def forward(addr: address):
    x: (Bytes[10], DynArray[uint256, 3]) = (b"hello", [1, 2, 3])
    extcall Target(addr).sink(x)
        """,
        # tuple literal built inline for a wildcard parameter. the wildcard
        # call return lands on the bounded member and resolves to it
        """
interface Target:
    def source_bytes() -> Bytes[...]: nonpayable
    def sink(x: (Bytes[10], DynArray[uint256, ...])): nonpayable

@external
def forward(addr: address):
    extcall Target(addr).sink((extcall Target(addr).source_bytes(), [1, 2, 3]))
        """,
        # wildcard tuple return assigned to a bounded local, then forwarded.
        # this is the supported way to pass a wildcard tuple return on to a
        # wildcard parameter, which cannot take the call directly
        """
interface Target:
    def source() -> (Bytes[...], DynArray[uint256, ...]): nonpayable
    def sink(x: (Bytes[10], DynArray[uint256, ...])): nonpayable

@external
def forward(addr: address):
    x: (Bytes[10], DynArray[uint256, 3]) = extcall Target(addr).source()
    extcall Target(addr).sink(x)
        """,
    ],
)
def test_wildcard_tuple_arg_roundtrip(get_contract, caller_code):
    target_code = """
b: Bytes[10]
xs: DynArray[uint256, 3]

@external
def source() -> (Bytes[INF], DynArray[uint256, INF]):
    return b"hello", [1, 2, 3]

@external
def source_bytes() -> Bytes[INF]:
    return b"hello"

@external
def sink(x: (Bytes[10], DynArray[uint256, 3])):
    self.b, self.xs = x

@external
@view
def stored() -> (Bytes[10], DynArray[uint256, 3]):
    return self.b, self.xs
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    caller.forward(target.address)
    assert target.stored() == (b"hello", [1, 2, 3])


def test_wildcard_tuple_return_discarded(get_contract):
    # with no expected type the wildcard tuple return resolves to INF members,
    # which is a valid return shape, so the discarded call stays legal
    target_code = """
calls: public(uint256)

@external
def source() -> (Bytes[INF], DynArray[uint256, INF]):
    self.calls += 1
    return b"hello", [1, 2, 3]
    """

    caller_code = """
interface Target:
    def source() -> (Bytes[...], DynArray[uint256, ...]): nonpayable

@external
def call_source(addr: address):
    extcall Target(addr).source()
    """

    target = get_contract(target_code)
    caller = get_contract(caller_code)
    caller.call_source(target.address)
    assert target.calls() == 1


def test_inf_dynarray_abi_encode_default_tuple(get_contract):
    payload = [i * 31 for i in range(2001)]
    code = """
@external
def enc(x: DynArray[uint256, INF]) -> Bytes[INF]:
    return abi_encode(x)
    """

    c = get_contract(code)
    assert c.enc(payload) == abi_encode("(uint256[])", (payload,))


def test_inf_dynarray_abi_encode_no_tuple(get_contract):
    payload = [i * 37 for i in range(2001)]
    code = """
@external
def enc(x: DynArray[uint256, INF]) -> Bytes[INF]:
    return abi_encode(x, ensure_tuple=False)
    """

    c = get_contract(code)
    assert c.enc(payload) == abi_encode("uint256[]", payload)


def test_inf_dynarray_abi_encode_method_id_and_static_args(get_contract):
    payload = [5, 8, 13, 21]
    code = """
@external
def enc(a: uint256, x: DynArray[uint256, INF], b: uint256) -> Bytes[INF]:
    return abi_encode(a, x, b, method_id=method_id("foo(uint256,uint256[],uint256)"))
    """

    c = get_contract(code)
    expected = method_id("foo(uint256,uint256[],uint256)")
    expected += abi_encode("(uint256,uint256[],uint256)", (11, payload, 22))
    assert c.enc(11, payload, 22) == expected


def test_inf_dynarray_abi_decode_default_tuple(get_contract):
    payload = [i * 41 for i in range(2001)]
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF])
    """

    c = get_contract(code)
    encoded = abi_encode("(uint256[])", (payload,))
    assert c.dec(encoded) == payload


def test_inf_dynarray_abi_decode_no_tuple(get_contract):
    payload = [i * 43 for i in range(2001)]
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF], unwrap_tuple=False)
    """

    c = get_contract(code)
    encoded = abi_encode("uint256[]", payload)
    assert c.dec(encoded) == payload


def test_inf_dynarray_abi_decode_rejects_malformed_payload(get_contract, tx_failed):
    code = """
@external
def dec(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF])

@external
def dec_no_tuple(x: Bytes[INF]) -> DynArray[uint256, INF]:
    return abi_decode(x, DynArray[uint256, INF], unwrap_tuple=False)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    assert c.dec(word(0)) == []

    for payload in [word(32), word(32) + word(2) + word(1)]:
        with tx_failed():
            c.dec(payload)

    with tx_failed():
        c.dec_no_tuple(word(2) + word(1))


def test_inf_dynarray_abi_encode_decode_local_roundtrip(get_contract):
    payload = [i * 47 for i in range(2001)]
    code = """
@external
def roundtrip(x: DynArray[uint256, INF]) -> DynArray[uint256, INF]:
    encoded: Bytes[INF] = abi_encode(x)
    return abi_decode(encoded, DynArray[uint256, INF])
    """

    c = get_contract(code)
    assert c.roundtrip(payload) == payload


def test_inf_dynarray_raw_create_snapshots_ctor_arg_before_pop(
    env, get_contract, compiler_settings
):
    child_code = """
stored_len: public(uint256)
popped: public(uint256)

@deploy
def __init__(xs: DynArray[uint256, INF], popped: uint256):
    self.stored_len = len(xs)
    self.popped = popped
    """
    out = compile_code(child_code, output_formats=["bytecode"], settings=compiler_settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], values: DynArray[uint256, INF]) -> address:
    xs: DynArray[uint256, INF] = values
    return raw_create(s, xs, xs.pop())
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(initcode, [11, 22, 33])

    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (3,)
    ret = env.message_call(addr, data=method_id("popped()"))
    assert abi_decode("(uint256)", ret) == (33,)


def test_inf_dynarray_raw_create_snapshots_ctor_arg_before_value_kwarg(
    env, get_contract, compiler_settings
):
    child_code = """
stored_len: public(uint256)
last: public(uint256)

@deploy
@payable
def __init__(xs: DynArray[uint256, INF]):
    self.stored_len = len(xs)
    self.last = xs[len(xs) - 1]
    """
    out = compile_code(child_code, output_formats=["bytecode"], settings=compiler_settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF], values: DynArray[uint256, INF]) -> (address, uint256):
    xs: DynArray[uint256, INF] = values
    addr: address = raw_create(s, xs, value=xs.pop())
    return addr, len(xs)
    """

    deployer = get_contract(deployer_code)
    addr, local_len = deployer.deploy(initcode, [11, 22, 0])
    assert local_len == 2

    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (3,)
    ret = env.message_call(addr, data=method_id("last()"))
    assert abi_decode("(uint256)", ret) == (0,)


def test_inf_dynarray_raw_create_freezes_bounded_ctor_arg_in_runtime_encoding(
    env, get_contract, compiler_settings
):
    child_code = """
stored_len_a: public(uint256)
stored_len_b: public(uint256)
popped: public(uint256)

@deploy
def __init__(
    a: DynArray[uint256, 3],
    b: DynArray[uint256, INF],
    popped: uint256
):
    self.stored_len_a = len(a)
    self.stored_len_b = len(b)
    self.popped = popped
    """
    out = compile_code(child_code, output_formats=["bytecode"], settings=compiler_settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x"))

    deployer_code = """
@external
def deploy(s: Bytes[INF]) -> (address, DynArray[uint256, 3], DynArray[uint256, INF]):
    a: DynArray[uint256, 3] = [4, 5, 6]
    b: DynArray[uint256, INF] = [1, 2, 3]
    addr: address = raw_create(s, a, b, a.pop())
    return addr, a, b
    """

    deployer = get_contract(deployer_code)
    addr, bounded, unbounded = deployer.deploy(initcode)
    assert bounded == [4, 5]
    assert unbounded == [1, 2, 3]

    ret = env.message_call(addr, data=method_id("stored_len_a()"))
    assert abi_decode("(uint256)", ret) == (3,)
    ret = env.message_call(addr, data=method_id("stored_len_b()"))
    assert abi_decode("(uint256)", ret) == (3,)
    ret = env.message_call(addr, data=method_id("popped()"))
    assert abi_decode("(uint256)", ret) == (6,)


def test_inf_dynarray_create_from_blueprint_unbounded_ctor_arg(
    env, get_contract, deploy_blueprint_for
):
    payload = [(i * 17) % 1000 for i in range(777)]
    child_code = """
stored_len: public(uint256)
first: public(uint256)
last: public(uint256)

@deploy
def __init__(x: DynArray[uint256, INF]):
    self.stored_len = len(x)
    self.first = x[0]
    self.last = x[len(x) - 1]
    """
    blueprint, _ = deploy_blueprint_for(child_code)

    deployer_code = """
@external
def deploy(target: address, x: DynArray[uint256, INF]) -> address:
    return create_from_blueprint(target, x)
    """

    deployer = get_contract(deployer_code)
    addr = deployer.deploy(blueprint.address, payload)
    assert abi_decode("(uint256)", env.message_call(addr, data=method_id("stored_len()"))) == (
        len(payload),
    )
    assert abi_decode("(uint256)", env.message_call(addr, data=method_id("first()"))) == (
        payload[0],
    )
    assert abi_decode("(uint256)", env.message_call(addr, data=method_id("last()"))) == (
        payload[-1],
    )


def test_inf_dynarray_create_from_blueprint_snapshots_ctor_arg_before_code_offset(
    env, get_contract, deploy_blueprint_for
):
    child_code = """
stored_len: public(uint256)
last: public(uint256)

@deploy
def __init__(x: DynArray[uint256, INF]):
    self.stored_len = len(x)
    self.last = x[len(x) - 1]
    """
    blueprint, _ = deploy_blueprint_for(child_code)

    deployer_code = """
@external
def deploy(target: address, values: DynArray[uint256, INF]) -> (address, uint256):
    x: DynArray[uint256, INF] = values
    addr: address = create_from_blueprint(target, x, code_offset=x.pop())
    return addr, len(x)
    """

    deployer = get_contract(deployer_code)
    addr, local_len = deployer.deploy(blueprint.address, [11, 22, 3])
    assert local_len == 2

    ret = env.message_call(addr, data=method_id("stored_len()"))
    assert abi_decode("(uint256)", ret) == (3,)
    ret = env.message_call(addr, data=method_id("last()"))
    assert abi_decode("(uint256)", ret) == (3,)


def test_inf_dynarray_internal_tuple_return_coerces_bounded_complex_member(
    get_contract, no_inlining_settings
):
    payload = bytes((i * 49) % 256 for i in range(2001))
    code = """
@internal
def _pair(x: Bytes[INF]) -> (DynArray[Bytes[65], 3], Bytes[INF]):
    y: DynArray[Bytes[33], 3] = [b"cat", b"kitten"]
    return y, x

@external
def pair(x: Bytes[INF]) -> (DynArray[Bytes[65], 3], Bytes[INF]):
    return self._pair(x)
    """

    c = get_contract(code, compiler_settings=no_inlining_settings)
    assert c.pair(payload) == ([b"cat", b"kitten"], payload)


def test_inf_dynarray_external_param_rejects_truncated_calldata(env, get_contract, tx_failed):
    code = """
@external
def length(x: DynArray[uint256, INF]) -> uint256:
    return len(x)
    """

    c = get_contract(code)

    def word(value):
        return value.to_bytes(32, "big")

    calldata = method_id("length(uint256[])") + word(32) + word(2) + word(1)
    with tx_failed():
        env.message_call(c.address, data=calldata)

    calldata = method_id("length(uint256[])") + word(0)
    assert abi_decode("(uint256)", env.message_call(c.address, data=calldata)) == (0,)
