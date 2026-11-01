"""
Dynamic memory of an external function starts above the static memory that
function can access, not above the largest static frame in the contract, so
calling a function which uses unbounded types does not pay memory expansion
for an unrelated function's large frame.
"""

import pytest

from vyper.compiler.settings import OptimizationLevel
from vyper.utils import keccak256


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


# an unrelated external function whose static frame grows with `bound`
# (about 128KB at bound 2048: memory expansion would cost ~45k gas)
def _big_entry(bound):
    return f"""
@external
@pure
def big(xs: DynArray[uint256, {bound}]) -> DynArray[uint256, {bound}]:
    return xs
"""


# `call` exercises the contract and returns the gas used by the call under test
def _assert_gas_independent_of_big_frame(get_contract, code, call):
    gas = {}
    for bound in (2, 2048):
        c = get_contract(code + _big_entry(bound))
        assert c.big([1, 2]) == [1, 2]
        gas[bound] = call(c)
    assert gas[2048] == gas[2]


def test_length_gas_independent_of_echo_bound(env, get_contract):
    code = """
BOUND: constant(uint256) = {bound}

@external
@pure
def echo(values: DynArray[Bytes[BOUND], 64]) -> DynArray[Bytes[BOUND], 64]:
    return values

@external
@pure
def length(data: Bytes[INF]) -> uint256:
    return len(data)
    """
    gas = {}
    for bound in (32, 1024):
        c = get_contract(code.format(bound=bound))
        assert c.echo([b"ab", b"c"]) == [b"ab", b"c"]
        assert c.length(b"\x01\x02\x03\x04") == 4
        gas[bound] = env.last_result.gas_used
    # echo's frame is about 135KB at bound 1024
    assert gas[1024] == gas[32]


@pytest.mark.parametrize("inline", [True, False])
def test_internal_function_shared_by_small_and_big_entries(
    env, get_contract, no_inlining_settings, inline
):
    # `_tag` keeps static locals live across its own dynamic allocations,
    # and its callers pass dynamic data into it: both the caller's data and
    # the callee's result must stay clear of the callee's frame
    code = """
@internal
def _tag(data: Bytes[INF], n: uint256) -> Bytes[INF]:
    words: uint256[4] = [n, n + 1, n + 2, n + 3]
    out: Bytes[INF] = concat(data, b"|")
    return concat(out, convert(words[0] + words[3], bytes32), data)

@external
def small(data: Bytes[INF]) -> Bytes[INF]:
    return self._tag(data, 1)

@external
def large(data: Bytes[INF], xs: DynArray[uint256, 2048]) -> Bytes[INF]:
    total: uint256 = 0
    for x: uint256 in xs:
        total += x
    return self._tag(data, total)
    """
    settings = {} if inline else {"compiler_settings": no_inlining_settings}
    payload = bytes(range(200))

    def expected(n):
        return payload + b"|" + (2 * n + 3).to_bytes(32, "big") + payload

    c = get_contract(code, **settings)
    assert c.small(payload) == expected(1)
    assert c.large(payload, [5, 6]) == expected(11)
    assert c.small(b"") == b"|" + (5).to_bytes(32, "big")

    def call(c):
        assert c.small(payload) == expected(1)
        return env.last_result.gas_used

    _assert_gas_independent_of_big_frame(lambda src: get_contract(src, **settings), code, call)


def test_kwargs_entry_points(env, get_contract):
    # each kwarg variant is a separate entry point into the same body
    code = """
@external
def tagged(
    data: Bytes[INF], suffix: Bytes[INF] = b"!", n: uint256 = 7
) -> (Bytes[INF], uint256):
    return concat(data, suffix), n
    """
    payload = b"\xaa" * 70

    def call(c):
        gas = []
        assert c.tagged(payload) == (payload + b"!", 7)
        gas.append(env.last_result.gas_used)
        assert c.tagged(payload, b"??") == (payload + b"??", 7)
        gas.append(env.last_result.gas_used)
        assert c.tagged(payload, b"", 3) == (payload, 3)
        gas.append(env.last_result.gas_used)
        return gas

    _assert_gas_independent_of_big_frame(get_contract, code, call)


def test_default_function(env, get_contract):
    code = """
size: public(uint256)
digest: public(bytes32)

@external
def __default__():
    data: Bytes[INF] = concat(msg.data, b"!")
    self.size = len(data)
    self.digest = keccak256(data)
    """
    payload = bytes(range(100))

    def call(c):
        env.message_call(c.address, data=payload)
        gas = env.last_result.gas_used
        assert c.size() == len(payload) + 1
        assert c.digest() == keccak256(payload + b"!")
        return gas

    _assert_gas_independent_of_big_frame(get_contract, code, call)


def test_dynamic_data_stays_clear_of_stack_spills(get_contract):
    # 16 arguments to an internal function spill the stack to memory at
    # O1; the dynamic `data` is live across the call and must not share
    # memory with the spill slots
    params = ", ".join(f"a{i}: uint256" for i in range(16))
    args = ", ".join(f"a{i}" for i in range(16))
    total = " + ".join(f"a{i}" for i in range(16))
    code = f"""
@internal
def sum_words({params}) -> uint256:
    return {total}

@external
def foo(data: Bytes[INF], {params}) -> (uint256, Bytes[INF]):
    s: uint256 = self.sum_words({args})
    return s, data
    """
    c = get_contract(code, override_opt_level=OptimizationLevel.O1)

    payload = bytes((i * 37) % 256 for i in range(300))
    values = list(range(1, 17))
    assert c.foo(payload, *values) == (sum(values), payload)
