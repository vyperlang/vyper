"""
End-to-end multicall contracts built on DynArray[T, INF] with ABI-dynamic
elements: an OpenZeppelin-style self-delegatecall batch and a
Multicall3-style aggregate over several targets.
"""

import pytest

from tests.evm_backends.abi import abi_encode
from vyper.utils import method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _word(value):
    return value.to_bytes(32, "big")


_MULTICALL_CODE = """
value: public(uint256)

@external
def set_value(v: uint256):
    self.value = v

@external
@view
def get_value() -> uint256:
    return self.value

@external
def add(a: uint256, b: uint256) -> uint256:
    return a + b

@external
def echo(s: String[64]) -> String[64]:
    return s

@external
def pair(a: uint256) -> (uint256, address):
    return a * 2, msg.sender

@external
def fail():
    raise "inner call failed"

@external
def multicall(data: DynArray[Bytes[1024], INF]) -> DynArray[Bytes[1024], INF]:
    results: DynArray[Bytes[1024], INF] = []
    for call: Bytes[1024] in data:
        results.append(raw_call(self, call, is_delegate_call=True, max_outsize=1024))
    return results
"""


def _call(sig, schema=None, args=()):
    data = method_id(sig)
    if schema is not None:
        data += abi_encode(schema, args)
    return data


def _batch(env, n):
    """n calls cycling through every target function, with expected results."""
    calls = []
    expected = []
    for i in range(n):
        kind = i % 5
        if kind == 0:
            calls.append(_call("set_value(uint256)", "(uint256)", (i + 1000,)))
            expected.append(b"")
        elif kind == 1:
            # the previous set_value ran as a delegatecall, so it wrote our storage
            calls.append(_call("get_value()"))
            expected.append(_word(i - 1 + 1000))
        elif kind == 2:
            calls.append(_call("add(uint256,uint256)", "(uint256,uint256)", (i, 2**128)))
            expected.append(_word(i + 2**128))
        elif kind == 3:
            s = f"call-{i}-" + "s" * (i % 50)
            calls.append(_call("echo(string)", "(string)", (s,)))
            expected.append(abi_encode("(string)", (s,)))
        else:
            calls.append(_call("pair(uint256)", "(uint256)", (i,)))
            expected.append(abi_encode("(uint256,address)", (2 * i, env.deployer)))
    return calls, expected


def test_multicall_abi_signature(get_contract):
    c = get_contract(_MULTICALL_CODE)
    (fn,) = [item for item in c.abi if item.get("name") == "multicall"]
    assert [i["type"] for i in fn["inputs"]] == ["bytes[]"]
    assert [o["type"] for o in fn["outputs"]] == ["bytes[]"]


@pytest.mark.parametrize("n", [0, 1, 5, 40])
def test_multicall_results(env, get_contract, n):
    c = get_contract(_MULTICALL_CODE)
    calls, expected = _batch(env, n)
    assert c.multicall(calls) == expected
    if n > 0:
        # last set_value in the batch persisted through the delegatecalls
        last_set = max(i for i in range(n) if i % 5 == 0)
        assert c.value() == last_set + 1000


def test_multicall_inner_failure_reverts_whole_batch(get_contract, tx_failed):
    c = get_contract(_MULTICALL_CODE)
    c.set_value(1)
    calls = [
        _call("set_value(uint256)", "(uint256)", (2,)),
        _call("fail()"),
        _call("set_value(uint256)", "(uint256)", (3,)),
    ]
    with tx_failed(exc_text="inner call failed"):
        c.multicall(calls)
    assert c.value() == 1

    with tx_failed():
        c.multicall([_call("no_such_function()")])
    assert c.value() == 1


def test_multicall_gas_growth(env, get_contract):
    # Informational: uniform batches so the per-call cost is comparable. The
    # per-call cost grows with the batch size because memory is never
    # reclaimed inside the call (decoded arguments, result buffers and
    # reallocated result arrays all stay allocated) and the memory expansion
    # cost is quadratic. Only a loose bound is asserted.
    c = get_contract(_MULTICALL_CODE)

    def run(n):
        calls = [_call("add(uint256,uint256)", "(uint256,uint256)", (i, 1)) for i in range(n)]
        assert c.multicall(calls) == [_word(i + 1) for i in range(n)]
        return env.last_result.gas_used

    gas5 = run(5)
    gas20 = run(20)
    gas40 = run(40)
    print(f"\n[multicall] n=5 gas_used={gas5}  n=20 gas_used={gas20}  n=40 gas_used={gas40}")
    marginal_early = (gas20 - gas5) / 15
    marginal_late = (gas40 - gas20) / 20
    assert marginal_late < 3 * marginal_early


_AGGREGATE_CODE = """
struct Batch:
    target: address
    allow_failure: bool
    call_data: Bytes[1024]

struct Result:
    success: bool
    return_data: Bytes[255]

@external
def aggregate(calls: DynArray[Batch, INF]) -> DynArray[Result, INF]:
    results: DynArray[Result, INF] = []
    for call: Batch in calls:
        success: bool = False
        ret: Bytes[255] = b""
        success, ret = raw_call(
            call.target, call.call_data, max_outsize=255, revert_on_failure=False
        )
        assert success or call.allow_failure, "aggregate: call failed"
        results.append(Result(success=success, return_data=ret))
    return results
"""

_COUNTER_CODE = """
count: public(uint256)

@external
def increment() -> uint256:
    self.count += 1
    return self.count

@external
def boom():
    raise "counter: boom"
"""

_STORE_CODE = """
names: HashMap[uint256, String[32]]

@external
def put(key: uint256, name: String[32]):
    self.names[key] = name

@external
@view
def get(key: uint256) -> String[32]:
    return self.names[key]

@external
def require_positive(x: int128) -> int128:
    assert x > 0, "store: not positive"
    return x
"""


def _error(msg):
    return method_id("Error(string)") + abi_encode("(string)", (msg,))


def test_aggregate_over_two_targets(env, get_contract):
    agg = get_contract(_AGGREGATE_CODE)
    counter = get_contract(_COUNTER_CODE)
    store = get_contract(_STORE_CODE)

    batch = [
        (counter.address, False, _call("increment()")),
        (store.address, False, _call("put(uint256,string)", "(uint256,string)", (7, "seven"))),
        (counter.address, True, _call("boom()")),
        (counter.address, False, _call("increment()")),
        (store.address, False, _call("get(uint256)", "(uint256)", (7,))),
        (store.address, True, _call("require_positive(int128)", "(int128)", (-3,))),
        (store.address, False, _call("require_positive(int128)", "(int128)", (3,))),
        (store.address, True, _call("no_such_function()")),
        (store.address, False, _call("get(uint256)", "(uint256)", (8,))),
    ]
    expected = [
        (True, _word(1)),
        (True, b""),
        (False, _error("counter: boom")),
        (True, _word(2)),
        (True, abi_encode("(string)", ("seven",))),
        (False, _error("store: not positive")),
        (True, (3).to_bytes(32, "big", signed=True)),
        (False, b""),
        (True, abi_encode("(string)", ("",))),
    ]
    assert agg.aggregate(batch) == expected
    assert counter.count() == 2
    assert store.get(7) == "seven"

    assert agg.aggregate([]) == []


def test_aggregate_failure_not_allowed_reverts(get_contract, tx_failed):
    agg = get_contract(_AGGREGATE_CODE)
    counter = get_contract(_COUNTER_CODE)

    batch = [
        (counter.address, False, _call("increment()")),
        (counter.address, False, _call("boom()")),
    ]
    with tx_failed(exc_text="aggregate: call failed"):
        agg.aggregate(batch)
    assert counter.count() == 0


def test_aggregate_many_calls(get_contract):
    agg = get_contract(_AGGREGATE_CODE)
    counter = get_contract(_COUNTER_CODE)
    store = get_contract(_STORE_CODE)

    batch = []
    expected = []
    for i in range(60):
        if i % 3 == 0:
            batch.append((counter.address, False, _call("increment()")))
            expected.append((True, _word(i // 3 + 1)))
        elif i % 3 == 1:
            name = f"n{i}" + "x" * (i % 29)
            put = _call("put(uint256,string)", "(uint256,string)", (i, name))
            batch.append((store.address, False, put))
            expected.append((True, b""))
        else:
            name = f"n{i - 1}" + "x" * ((i - 1) % 29)
            batch.append((store.address, False, _call("get(uint256)", "(uint256)", (i - 1,))))
            expected.append((True, abi_encode("(string)", (name,))))
    assert agg.aggregate(batch) == expected
    assert counter.count() == 20
