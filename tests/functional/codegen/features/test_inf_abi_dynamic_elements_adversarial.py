"""
Adversarial and end-to-end tests for DynArray[T, INF] with ABI-dynamic element
types (Bytes[N], String[N], bounded DynArray, structs with bytestrings).

The smoke tests live in test_inf_abi_dynamic_elements.py. This file covers
malformed input on every ingress path (calldata, returndata, abi_decode),
widening from narrower bounded element types, ABI encoding with mixed
arguments, and event, custom error, create_from_blueprint and print
arguments.
"""

import pytest

from tests.evm_backends.abi import abi_decode, abi_encode
from tests.evm_backends.base_env import EvmError, ExecutionReverted
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.exceptions import TypeMismatch
from vyper.utils import keccak256, method_id


@pytest.fixture(autouse=True)
def _venom_only(experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")


def _word(value):
    return value.to_bytes(32, "big")


def _deploy_raw_returner(env, payload):
    # runtime code: CODECOPY the trailing payload to memory and RETURN it
    assert len(payload) < 2**16
    size = len(payload).to_bytes(2, "big")
    runtime = b"\x61" + size + b"\x60\x0e\x60\x00\x39\x61" + size + b"\x60\x00\xf3"
    assert len(runtime) == 14
    runtime += payload
    initcode = bytes.fromhex(f"61{len(runtime):04x}3d81600a3d39f3") + runtime
    return env.deploy([], initcode)


def _deploy_with_ctor_data(env, code, ctor_data, settings):
    out = compile_code(code, output_formats=["abi", "bytecode"], settings=settings)
    initcode = bytes.fromhex(out["bytecode"].removeprefix("0x")) + ctor_data
    return env.deploy(out["abi"], initcode)


def _revert_data(excinfo):
    revert_hex = excinfo.value.args[0]
    assert revert_hex.startswith("0x")
    return bytes.fromhex(revert_hex[2:])


def _body(count, heads, tail=b""):
    """ABI payload of a bytes[] starting at its count word.

    `heads` are element offsets relative to the first head word.
    """
    return _word(count) + b"".join(_word(h) for h in heads) + tail


# Malformed and non-canonical bytes[] payloads for DynArray[Bytes[512], INF].
# `expected` is None when decoding must be rejected, else the decoded list.
_MALFORMED_CASES = [
    # element head offsets
    ("head_wraps_to_before_payload", _body(1, [2**256 - 32]), None),
    ("head_wraps_to_count_word", _body(1, [2**256 - 64], _word(1)), None),
    ("head_at_end_of_payload", _body(1, [32]), None),
    ("head_length_word_only_no_data", _body(1, [32], _word(5)), None),
    ("head_tail_truncated_by_one_byte", _body(1, [32], _word(33) + b"a" * 32), None),
    ("head_tail_unpadded_exact_fit", _body(1, [32], _word(33) + b"a" * 33), [b"a" * 33]),
    ("head_tail_ends_at_payload_end", _body(1, [32], _word(32) + b"z" * 32), [b"z" * 32]),
    (
        "head_aliases_sibling_tail",
        _body(2, [64, 96], _word(35) + _word(3) + b"abc".ljust(32, b"\0")),
        [_word(3) + b"abc", b"abc"],
    ),
    ("head_far_past_payload", _body(1, [2**64], _word(1) + b"q".ljust(32, b"\0")), None),
    ("head_not_word_aligned", _body(1, [33], b"\0" + _word(4) + b"abcd" + bytes(27)), [b"abcd"]),
    # element count
    ("count_one_past_payload", _body(6, [128, 128, 128, 128, 0]), None),
    (
        "count_fills_payload_with_aliased_heads",
        _body(5, [128, 128, 128, 128, 0]),
        [b"", b"", b"", b"", _word(128) * 3 + _word(0)],
    ),
    ("count_high_bit_set", _body(2**255 + 3, [96, 96, 96], _word(0)), None),
    ("count_zero_with_trailing_garbage", _body(0, [], b"\xff" * 77), []),
    # element lengths
    ("elem_len_one_over_max", _body(1, [32], _word(513) + b"b" * 513 + bytes(31)), None),
    ("elem_len_at_max", _body(1, [32], _word(512) + b"b" * 512), [b"b" * 512]),
    ("elem_len_huge", _body(1, [32], _word(2**255) + b"c" * 32), None),
]

_INGRESS_PATHS = ("calldata", "returndata", "abi_decode")

_INGRESS_CODE = """
interface Source:
    def data() -> DynArray[Bytes[512], INF]: view

@external
def from_calldata(xs: DynArray[Bytes[512], INF]) -> DynArray[Bytes[512], INF]:
    return xs

@external
def from_bytes(data: Bytes[INF]) -> DynArray[Bytes[512], INF]:
    return abi_decode(data, DynArray[Bytes[512], INF])

@external
def from_returndata(addr: address) -> DynArray[Bytes[512], INF]:
    return staticcall Source(addr).data()

@external
def from_calldata_bounded(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[512], 5]:
    return xs

@external
def from_bytes_bounded(data: Bytes[3000]) -> DynArray[Bytes[512], 5]:
    return abi_decode(data, DynArray[Bytes[512], 5])
"""


@pytest.fixture(scope="module")
def ingress(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")
    return get_contract(_INGRESS_CODE)


def _run_ingress(env, c, path, body, gas=None):
    payload = _word(32) + body
    if path == "calldata":
        ret = env.message_call(
            c.address, data=method_id("from_calldata(bytes[])") + payload, gas=gas
        )
        return abi_decode("(bytes[])", ret)[0]
    if path == "returndata":
        target = _deploy_raw_returner(env, payload)
        return c.from_returndata(target.address, gas=gas)
    assert path == "abi_decode"
    return c.from_bytes(payload, gas=gas)


def _run_ingress_bounded(env, c, path, body):
    payload = _word(32) + body
    if path == "calldata":
        selector = method_id("from_calldata_bounded(bytes[])")
        ret = env.message_call(c.address, data=selector + payload)
        return abi_decode("(bytes[])", ret)[0]
    assert path == "abi_decode"
    return c.from_bytes_bounded(payload)


@pytest.mark.parametrize(
    ("body", "expected"),
    [pytest.param(body, expected, id=name) for name, body, expected in _MALFORMED_CASES],
)
def test_malformed_input_same_outcome_on_every_ingress_path(
    env, ingress, tx_failed, body, expected
):
    for path in _INGRESS_PATHS:
        if expected is None:
            with tx_failed(EvmError):
                _run_ingress(env, ingress, path, body)
        else:
            assert _run_ingress(env, ingress, path, body) == expected, path


def test_malformed_input_rejection_is_a_plain_revert(env, ingress):
    # Every rejected case reverts (no out-of-gas) on every path, except a head
    # offset far past the payload on the memory-backed paths, see
    # test_far_head_offset_out_of_gas_on_memory_paths.
    for name, body, expected in _MALFORMED_CASES:
        if expected is not None or name == "head_far_past_payload":
            continue
        for path in _INGRESS_PATHS:
            with pytest.raises(ExecutionReverted):
                _run_ingress(env, ingress, path, body, gas=1_000_000)


def test_far_head_offset_out_of_gas_on_memory_paths(env, ingress):
    # A head offset far past the payload. Calldata reads past its end as
    # zeros, so the calldata path fails its bounds check and reverts. The
    # memory-backed paths load the element length word from the offset
    # before checking it against the payload end, and that memory access
    # runs out of gas. The bounded decoder behaves the same way on the same
    # input.
    body = _body(1, [2**64], _word(1) + b"q".ljust(32, b"\0"))

    with pytest.raises(ExecutionReverted):
        _run_ingress(env, ingress, "calldata", body)

    for path in ("returndata", "abi_decode"):
        with pytest.raises(EvmError) as excinfo:
            _run_ingress(env, ingress, path, body)
        assert not isinstance(excinfo.value, ExecutionReverted), path

    with pytest.raises(EvmError) as excinfo:
        _run_ingress_bounded(env, ingress, "abi_decode", body)
    assert not isinstance(excinfo.value, ExecutionReverted)


def test_huge_element_length_reverts_cheaply(env, ingress):
    # The element length word is checked against the type bound before any
    # element data is touched, so a claimed length of 2**255 does not expand
    # memory: the call reverts (rather than running out of gas) within a
    # modest gas budget.
    body = _body(1, [32], _word(2**255) + b"c" * 32)
    for path in _INGRESS_PATHS:
        with pytest.raises(ExecutionReverted):
            _run_ingress(env, ingress, path, body, gas=500_000)


@pytest.mark.parametrize("path", ["calldata", "abi_decode"])
def test_non_word_aligned_head_matches_bounded_decoder(env, ingress, path):
    body = _body(1, [33], b"\0" + _word(4) + b"abcd" + bytes(27))
    assert _run_ingress(env, ingress, path, body) == [b"abcd"]
    assert _run_ingress_bounded(env, ingress, path, body) == [b"abcd"]


@pytest.mark.parametrize("path", ["calldata", "abi_decode"])
def test_aliased_heads_match_bounded_decoder(env, ingress, path):
    body = _body(5, [128, 128, 128, 128, 0])
    expected = [b"", b"", b"", b"", _word(128) * 3 + _word(0)]
    assert _run_ingress(env, ingress, path, body) == expected
    assert _run_ingress_bounded(env, ingress, path, body) == expected


def test_truncated_tail_rejected_by_inf_but_zero_filled_by_bounded_calldata(env, ingress):
    # Bounded calldata arguments keep the lenient legacy decode: bytes past
    # the end of calldata read as zeros. The INF decoder bounds every
    # element against calldatasize and rejects the same input.
    body = _body(1, [32], _word(40) + b"a" * 32)
    with pytest.raises(ExecutionReverted):
        _run_ingress(env, ingress, "calldata", body)
    assert _run_ingress_bounded(env, ingress, "calldata", body) == [b"a" * 32 + bytes(8)]
    # from memory both decoders reject it
    with pytest.raises(ExecutionReverted):
        _run_ingress(env, ingress, "abi_decode", body)
    with pytest.raises(ExecutionReverted):
        _run_ingress_bounded(env, ingress, "abi_decode", body)


_STRUCT_INGRESS_CODE = """
struct Item:
    id: uint256
    data: Bytes[64]

interface Source:
    def data() -> DynArray[Item, INF]: view

@external
def from_calldata(xs: DynArray[Item, INF]) -> DynArray[Item, INF]:
    return xs

@external
def from_bytes(data: Bytes[INF]) -> DynArray[Item, INF]:
    return abi_decode(data, DynArray[Item, INF])

@external
def from_returndata(addr: address) -> DynArray[Item, INF]:
    return staticcall Source(addr).data()
"""


def _item_tail(item_id, data_head, data):
    return _word(item_id) + _word(data_head) + data


# (uint256,bytes)[] payloads for DynArray[Item, INF]: the struct's own head
# offsets (relative to the struct start) can be malformed independently of
# the outer element heads.
_STRUCT_CASES = [
    (
        "canonical",
        abi_encode("((uint256,bytes)[])", ([(1, b"one"), (2, b"")],))[32:],
        [(1, b"one"), (2, b"")],
    ),
    # inner bytes head points past the payload
    ("inner_head_past_payload", _body(1, [32], _item_tail(1, 0x1000, b"")), None),
    # inner bytes head wraps to before the struct
    ("inner_head_wraps", _body(1, [32], _item_tail(1, 2**256 - 32, b"")), None),
    # inner bytes tail truncated
    ("inner_tail_truncated", _body(1, [32], _item_tail(1, 64, _word(40) + b"a" * 32)), None),
    # inner bytes longer than Bytes[64]
    ("inner_len_over_max", _body(1, [32], _item_tail(1, 64, _word(65) + b"a" * 96)), None),
    # inner bytes head points at the struct's own id word: length 3 -> reads the head word bytes
    ("inner_head_aliases_struct_id", _body(1, [32], _item_tail(3, 0, b"")), [(3, b"\0\0\0")]),
    # struct static part (two words) does not fit the payload
    ("struct_head_only", _body(1, [32], _word(1)), None),
    # element head 0 lands on the head word itself: id = 0 (the head value), inner head = 1
    # points one byte into the struct, where the 32-byte length word reads as 0
    ("elem_head_zero", _body(1, [0], _word(1)), [(0, b"")]),
]


@pytest.fixture(scope="module")
def struct_ingress(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")
    return get_contract(_STRUCT_INGRESS_CODE)


def _run_struct_ingress(env, c, path, body):
    payload = _word(32) + body
    if path == "calldata":
        ret = env.message_call(
            c.address, data=method_id("from_calldata((uint256,bytes)[])") + payload
        )
        return abi_decode("((uint256,bytes)[])", ret)[0]
    if path == "returndata":
        target = _deploy_raw_returner(env, payload)
        return c.from_returndata(target.address)
    assert path == "abi_decode"
    return c.from_bytes(payload)


@pytest.mark.parametrize(
    ("body", "expected"),
    [pytest.param(body, expected, id=name) for name, body, expected in _STRUCT_CASES],
)
def test_struct_elements_malformed_input_same_outcome_on_every_ingress_path(
    env, struct_ingress, tx_failed, body, expected
):
    for path in _INGRESS_PATHS:
        if expected is None:
            with tx_failed():
                _run_struct_ingress(env, struct_ingress, path, body)
        else:
            assert _run_struct_ingress(env, struct_ingress, path, body) == expected, path


def test_nested_dynarray_elements_malformed_input(env, get_contract, tx_failed):
    code = """
@external
def from_calldata(xs: DynArray[DynArray[uint256, 3], INF]) -> DynArray[DynArray[uint256, 3], INF]:
    return xs

@external
def from_bytes(data: Bytes[INF]) -> DynArray[DynArray[uint256, 3], INF]:
    return abi_decode(data, DynArray[DynArray[uint256, 3], INF])
    """
    c = get_contract(code)

    def run(path, body):
        payload = _word(32) + body
        if path == "calldata":
            selector = method_id("from_calldata(uint256[][])")
            ret = env.message_call(c.address, data=selector + payload)
            return abi_decode("(uint256[][])", ret)[0]
        return c.from_bytes(payload)

    ok = _body(2, [64, 64 + 32 * 3], _word(2) + _word(7) + _word(8) + _word(0))
    inner_count_over_max = _body(1, [32], _word(4) + _word(1) * 4)
    inner_count_past_payload = _body(1, [32], _word(3) + _word(1) * 2)
    inner_head_past_payload = _body(1, [0x2000])
    # both inner heads point at the first head word, whose value 0 is read as the inner count
    inner_alias_heads = _body(2, [0, 0])

    for path in ("calldata", "abi_decode"):
        assert run(path, ok) == [[7, 8], []]
        assert run(path, inner_alias_heads) == [[], []]
        for body in (inner_count_over_max, inner_count_past_payload, inner_head_past_payload):
            with tx_failed():
                run(path, body)


def test_constructor_arg_with_dynamic_elements(get_contract):
    code = """
stored_len: public(uint256)
first: public(Bytes[512])
last: public(Bytes[512])
total: public(uint256)

@deploy
def __init__(xs: DynArray[Bytes[512], INF]):
    self.stored_len = len(xs)
    self.first = xs[0]
    self.last = xs[len(xs) - 1]
    for x: Bytes[512] in xs:
        self.total += len(x)
    """
    payload = [b"first", b"", b"x" * 512, b"last!"]
    c = get_contract(code, payload)
    assert c.stored_len() == 4
    assert c.first() == b"first"
    assert c.last() == b"last!"
    assert c.total() == 5 + 0 + 512 + 5


def test_constructor_arg_accepts_aliased_heads(env, compiler_settings):
    code = """
stored: public(DynArray[Bytes[512], 8])

@deploy
def __init__(xs: DynArray[Bytes[512], INF]):
    for x: Bytes[512] in xs:
        self.stored.append(x)
    """
    body = _body(5, [128, 128, 128, 128, 0])
    c = _deploy_with_ctor_data(env, code, _word(32) + body, compiler_settings)
    expected = [b"", b"", b"", b"", _word(128) * 3 + _word(0)]
    for i, x in enumerate(expected):
        assert c.stored(i) == x


def test_decode_cost_of_max_aliased_count(env, get_contract):
    # Informational: a ~4KB payload can claim 129 elements of Bytes[4096]
    # whose heads all alias one another. It must decode, and decoding must
    # fit a generous gas budget. Element 128's tail spans the head words
    # 1..128; every other element points at the last head word (value 0).
    code = """
@external
def summarize(xs: DynArray[Bytes[4096], INF]) -> (uint256, uint256, bytes32):
    total: uint256 = 0
    for x: Bytes[4096] in xs:
        total += len(x)
    return len(xs), total, keccak256(xs[len(xs) - 1])
    """
    c = get_contract(code)

    k = 129
    body = _body(k, [32 * (k - 1)] * (k - 1) + [0])
    assert len(body) == 32 + 32 * k
    last = _word(32 * (k - 1)) * (k - 2) + _word(0)
    assert len(last) == 4096

    ret = env.message_call(
        c.address, data=method_id("summarize(bytes[])") + _word(32) + body, gas=30_000_000
    )
    assert abi_decode("(uint256,uint256,bytes32)", ret) == (k, 4096, keccak256(last))


# event, custom error, create_from_blueprint and print arguments of DynArray[String[64], INF]


_STRINGS = ["", "a", "z" * 64, "hello world", "x" * 63]


def test_string_array_event(env, get_contract):
    code = """
event Words:
    n: uint256
    words: DynArray[String[64], INF]
    tag: String[8]

@external
def emit_words(words: DynArray[String[64], INF]):
    log Words(n=len(words), words=words, tag="tag")
    """
    c = get_contract(code)
    c.emit_words(_STRINGS)
    (log,) = env.get_logs(c)
    assert log.event == "Words"
    assert log.args.n == len(_STRINGS)
    assert log.args.words == _STRINGS
    assert log.args.tag == "tag"
    assert log.raw_data == abi_encode("(uint256,string[],string)", (len(_STRINGS), _STRINGS, "tag"))

    c.emit_words([])
    (log,) = env.get_logs(c)
    assert log.args.words == []


@pytest.mark.parametrize("words", [[], ["only"], _STRINGS])
def test_string_array_custom_error(get_contract, words):
    code = """
error Words:
    words: DynArray[String[64], INF]

error Mixed:
    a: uint256
    words: DynArray[String[64], INF]
    b: Bytes[8]

@external
def boom(words: DynArray[String[64], INF]):
    raise Words(words)

@external
def boom_mixed(words: DynArray[String[64], INF]):
    raise Mixed(a=1, words=words, b=b"end")
    """
    c = get_contract(code)

    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom(words)
    assert _revert_data(excinfo) == method_id("Words(string[])") + abi_encode(
        "(string[])", (words,)
    )

    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom_mixed(words)
    assert _revert_data(excinfo) == method_id("Mixed(uint256,string[],bytes)") + abi_encode(
        "(uint256,string[],bytes)", (1, words, b"end")
    )


def test_string_array_create_from_blueprint_ctor_arg(env, get_contract, deploy_blueprint_for):
    child_code = """
stored_len: public(uint256)
first: public(String[64])
last: public(String[64])

@deploy
def __init__(words: DynArray[String[64], INF]):
    self.stored_len = len(words)
    self.first = words[0]
    self.last = words[len(words) - 1]
    """
    blueprint, _ = deploy_blueprint_for(child_code)

    deployer_code = """
@external
def deploy(target: address, words: DynArray[String[64], INF]) -> address:
    return create_from_blueprint(target, words)

@external
def deploy_widened(target: address, words: DynArray[String[5], 3]) -> address:
    return create_from_blueprint(target, words)
    """
    deployer = get_contract(deployer_code)

    def read(addr, sig, schema):
        return abi_decode(schema, env.message_call(addr, data=method_id(sig)))[0]

    addr = deployer.deploy(blueprint.address, _STRINGS)
    assert read(addr, "stored_len()", "(uint256)") == len(_STRINGS)
    assert read(addr, "first()", "(string)") == _STRINGS[0]
    assert read(addr, "last()", "(string)") == _STRINGS[-1]

    addr = deployer.deploy_widened(blueprint.address, ["abcde", "", "xy"])
    assert read(addr, "stored_len()", "(uint256)") == 3
    assert read(addr, "first()", "(string)") == "abcde"
    assert read(addr, "last()", "(string)") == "xy"


def test_string_array_print(get_contract):
    # The test harness cannot observe console output; this checks that
    # print() compiles and does not disturb the value.
    code = """
@external
def log_values(words: DynArray[String[64], INF]) -> (uint256, String[64]):
    print(words)
    print(words, hardhat_compat=True)
    return len(words), words[len(words) - 1]
    """
    c = get_contract(code)
    assert c.log_values(_STRINGS) == (len(_STRINGS), _STRINGS[-1])


# abi_encode with method_id and mixed bounded / unbounded arguments


@pytest.mark.parametrize(
    "xs",
    [
        [],
        [b""],
        [b"a", b"", b"bb"],
        [b"x" * 512, b"y" * 511, b"z" * 33],
        [bytes([i]) * (i * 7 % 513) for i in range(40)],
    ],
)
@pytest.mark.parametrize("tail", [b"", b"t", b"T" * 100])
def test_abi_encode_mixed_args_with_method_id(get_contract, xs, tail):
    code = """
@external
def enc(a: uint256, xs: DynArray[Bytes[512], INF], b: Bytes[100]) -> Bytes[INF]:
    return abi_encode(a, xs, b, method_id=method_id("foo(uint256,bytes[],bytes)"))

@external
def enc_plain(a: uint256, xs: DynArray[Bytes[512], INF], b: Bytes[100]) -> Bytes[INF]:
    return abi_encode(a, xs, b)

@external
def enc_strings(xs: DynArray[String[64], INF], b: uint8) -> Bytes[INF]:
    return abi_encode(xs, b, method_id=method_id("bar(string[],uint8)"))
    """
    c = get_contract(code)
    a = 2**200 + 7
    expected = abi_encode("(uint256,bytes[],bytes)", (a, xs, tail))
    assert c.enc(a, xs, tail) == method_id("foo(uint256,bytes[],bytes)") + expected
    assert c.enc_plain(a, xs, tail) == expected

    strings = [x[:32].hex() for x in xs]
    assert c.enc_strings(strings, 200) == method_id("bar(string[],uint8)") + abi_encode(
        "(string[],uint8)", (strings, 200)
    )


# Widening: DynArray[Bytes[10], 3] -> DynArray[Bytes[512], INF]. Every test
# checks the full contents of every element, not only the length.


_WIDEN_PAYLOADS = [[], [b"0123456789"], [b"0123456789", b"", b"abc"], [b"", b"", b""]]
_BIG = b"\x01" * 512


@pytest.mark.parametrize("payload", _WIDEN_PAYLOADS)
def test_widened_assignment_full_contents(get_contract, payload):
    code = """
@external
def nth(xs: DynArray[Bytes[10], 3], big: Bytes[512], i: uint256) -> Bytes[512]:
    ys: DynArray[Bytes[512], INF] = xs
    ys.append(big)
    return ys[i]

@external
def all_elems(xs: DynArray[Bytes[10], 3], big: Bytes[512]) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    ys.append(big)
    if len(xs) > 0:
        ys.append(xs[len(xs) - 1])
    else:
        ys.append(b"none")
    return ys

@external
def reassign(
    xs: DynArray[Bytes[10], 3], ws: DynArray[Bytes[4], 2], big: Bytes[512]
) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    ys = ws
    ys.append(big)
    return ys
    """
    c = get_contract(code)
    expected = payload + [_BIG]
    for i, x in enumerate(expected):
        assert c.nth(payload, _BIG, i) == x
    tail = payload[-1] if len(payload) > 0 else b"none"
    assert c.all_elems(payload, _BIG) == expected + [tail]
    assert c.reassign(payload, [b"abcd", b""], _BIG) == [b"abcd", b"", _BIG]


@pytest.mark.parametrize("payload", _WIDEN_PAYLOADS)
@pytest.mark.parametrize("inline", [True, False])
def test_widened_internal_call_arg_and_return_full_contents(
    get_contract, no_inlining_settings, payload, inline
):
    code = """
@internal
def _nth(xs: DynArray[Bytes[512], INF], i: uint256) -> Bytes[512]:
    return xs[i]

@internal
def _extend(xs: DynArray[Bytes[512], INF], big: Bytes[512]) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    ys.append(big)
    return ys

@internal
def _narrow_copy(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[10], 3]:
    return xs

@internal
def _widen(xs: DynArray[Bytes[10], 3]) -> DynArray[Bytes[512], INF]:
    return xs

@external
def nth(xs: DynArray[Bytes[10], 3], i: uint256) -> Bytes[512]:
    return self._nth(xs, i)

@external
def extend(xs: DynArray[Bytes[10], 3], big: Bytes[512]) -> DynArray[Bytes[512], INF]:
    return self._extend(xs, big)

@external
def from_narrow_return(xs: DynArray[Bytes[10], 3], big: Bytes[512]) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = self._narrow_copy(xs)
    ys.append(big)
    return ys

@external
def widen_then_nth(xs: DynArray[Bytes[10], 3], big: Bytes[512], i: uint256) -> Bytes[512]:
    ys: DynArray[Bytes[512], INF] = self._widen(xs)
    ys.append(big)
    return ys[i]
    """
    kwargs = {} if inline else {"compiler_settings": no_inlining_settings}
    c = get_contract(code, **kwargs)
    for i, x in enumerate(payload):
        assert c.nth(payload, i) == x
    assert c.extend(payload, _BIG) == payload + [_BIG]
    assert c.from_narrow_return(payload, _BIG) == payload + [_BIG]
    for i, x in enumerate(payload + [_BIG]):
        assert c.widen_then_nth(payload, _BIG, i) == x


@pytest.mark.parametrize("inline", [True, False])
def test_widened_tuple_return_full_contents(get_contract, no_inlining_settings, inline):
    code = """
@internal
def _pair() -> (uint256, DynArray[Bytes[10], 3]):
    return 7, [b"0123456789", b"", b"abc"]

@internal
def _triple(xs: DynArray[Bytes[10], 3]) -> (Bytes[4], DynArray[Bytes[10], 3], uint256):
    return b"pre", xs, len(xs)

@external
def pair() -> (uint256, DynArray[Bytes[512], INF]):
    return self._pair()

@external
def pair_unpacked(big: Bytes[512]) -> (uint256, DynArray[Bytes[512], INF]):
    n: uint256 = 0
    ys: DynArray[Bytes[512], INF] = []
    n, ys = self._pair()
    ys.append(big)
    return n, ys

@external
def triple(xs: DynArray[Bytes[10], 3]) -> (Bytes[4], DynArray[Bytes[512], INF], uint256):
    return self._triple(xs)

@external
def literal(xs: DynArray[Bytes[10], 3]) -> (uint256, DynArray[Bytes[512], INF], uint256):
    return len(xs), xs, 99
    """
    kwargs = {} if inline else {"compiler_settings": no_inlining_settings}
    c = get_contract(code, **kwargs)
    assert c.pair() == (7, [b"0123456789", b"", b"abc"])
    assert c.pair_unpacked(_BIG) == (7, [b"0123456789", b"", b"abc", _BIG])
    for payload in _WIDEN_PAYLOADS:
        assert c.triple(payload) == (b"pre", payload, len(payload))
        assert c.literal(payload) == (len(payload), payload, 99)


def test_widened_kwarg_defaults_full_contents(get_contract):
    code = """
@internal
def _with_default(
    big: Bytes[512], xs: DynArray[Bytes[512], INF] = [b"0123456789", b"", b"abc"]
) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    ys.append(big)
    return ys

@external
def external_default(
    big: Bytes[512], xs: DynArray[Bytes[512], INF] = [b"0123456789", b"", b"abc"]
) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = xs
    ys.append(big)
    return ys

@external
def internal_default(big: Bytes[512]) -> DynArray[Bytes[512], INF]:
    return self._with_default(big)

@external
def internal_provided(big: Bytes[512], xs: DynArray[Bytes[4], 2]) -> DynArray[Bytes[512], INF]:
    return self._with_default(big, xs)
    """
    c = get_contract(code)
    assert c.external_default(_BIG) == [b"0123456789", b"", b"abc", _BIG]
    assert c.external_default(_BIG, [b"q" * 512]) == [b"q" * 512, _BIG]
    assert c.external_default(_BIG, []) == [_BIG]
    assert c.internal_default(_BIG) == [b"0123456789", b"", b"abc", _BIG]
    assert c.internal_provided(_BIG, [b"abcd", b""]) == [b"abcd", b"", _BIG]


def test_widened_default_return_value_full_contents(env, get_contract):
    code = """
interface Source:
    def data() -> DynArray[Bytes[512], INF]: view

@external
def get(
    addr: address, fallback: DynArray[Bytes[10], 3], big: Bytes[512]
) -> DynArray[Bytes[512], INF]:
    ys: DynArray[Bytes[512], INF] = staticcall Source(addr).data(default_return_value=fallback)
    ys.append(big)
    return ys
    """
    c = get_contract(code)
    empty_target = _deploy_raw_returner(env, b"")
    for payload in _WIDEN_PAYLOADS:
        assert c.get(empty_target.address, payload, _BIG) == payload + [_BIG]

    target = _deploy_raw_returner(env, abi_encode("(bytes[])", ([b"real", b"r" * 512],)))
    assert c.get(target.address, [b"0123456789"], _BIG) == [b"real", b"r" * 512, _BIG]


@pytest.mark.parametrize("payload", _WIDEN_PAYLOADS)
def test_widened_event_and_custom_error_full_contents(env, get_contract, payload):
    code = """
event E:
    xs: DynArray[Bytes[512], INF]
    n: uint256

error Oops:
    n: uint256
    xs: DynArray[Bytes[512], INF]

@external
def emit_event(xs: DynArray[Bytes[10], 3]):
    log E(xs=xs, n=len(xs))

@external
def boom(xs: DynArray[Bytes[10], 3]):
    raise Oops(len(xs), xs)
    """
    c = get_contract(code)
    c.emit_event(payload)
    (log,) = env.get_logs(c)
    assert log.args.xs == payload
    assert log.args.n == len(payload)
    assert log.raw_data == abi_encode("(bytes[],uint256)", (payload, len(payload)))

    with pytest.raises(ExecutionReverted) as excinfo:
        c.boom(payload)
    assert _revert_data(excinfo) == method_id("Oops(uint256,bytes[])") + abi_encode(
        "(uint256,bytes[])", (len(payload), payload)
    )


def test_widened_string_elements_full_contents(get_contract):
    code = """
@external
def widen(xs: DynArray[String[5], 2], big: String[64]) -> DynArray[String[64], INF]:
    ys: DynArray[String[64], INF] = xs
    ys.append(big)
    return ys

@external
def nth(xs: DynArray[String[5], 2], i: uint256) -> String[64]:
    ys: DynArray[String[64], INF] = xs
    return ys[i]
    """
    c = get_contract(code)
    payload = ["abcde", ""]
    assert c.widen(payload, "y" * 64) == payload + ["y" * 64]
    assert c.widen([], "y" * 64) == ["y" * 64]
    assert c.nth(payload, 0) == "abcde"
    assert c.nth(payload, 1) == ""


@pytest.mark.parametrize("payload", [[], [[1, 2], [], [3]], [[9, 8], [7, 6], [5, 4]]])
def test_widened_nested_dynarray_full_contents(get_contract, payload):
    code = """
@internal
def _sum(xs: DynArray[DynArray[uint256, 4], INF]) -> uint256:
    s: uint256 = 0
    for row: DynArray[uint256, 4] in xs:
        for v: uint256 in row:
            s += v
    return s

@external
def widen(xs: DynArray[DynArray[uint256, 2], 3]) -> DynArray[DynArray[uint256, 4], INF]:
    ys: DynArray[DynArray[uint256, 4], INF] = xs
    ys.append([10, 20, 30, 40])
    ys.append([])
    return ys

@external
def cell(xs: DynArray[DynArray[uint256, 2], 3], i: uint256, j: uint256) -> uint256:
    ys: DynArray[DynArray[uint256, 4], INF] = xs
    return ys[i][j]

@external
def row_len(xs: DynArray[DynArray[uint256, 2], 3], i: uint256) -> uint256:
    ys: DynArray[DynArray[uint256, 4], INF] = xs
    ys.append([10, 20, 30, 40])
    return len(ys[i])

@external
def total(xs: DynArray[DynArray[uint256, 2], 3]) -> uint256:
    return self._sum(xs)
    """
    c = get_contract(code)
    assert c.widen(payload) == payload + [[10, 20, 30, 40], []]
    for i, row in enumerate(payload):
        assert c.row_len(payload, i) == len(row)
        for j, v in enumerate(row):
            assert c.cell(payload, i, j) == v
    assert c.row_len(payload, len(payload)) == 4
    assert c.total(payload) == sum(sum(row) for row in payload)


@pytest.mark.parametrize(
    "code",
    [
        # narrowing the element type is never allowed
        """
@external
def f(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[10], INF]:
    ys: DynArray[Bytes[10], INF] = xs
    return ys
    """,
        """
@external
def f(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[10], INF]:
    return xs
    """,
        """
@external
def f(xs: DynArray[Bytes[512], INF]) -> DynArray[Bytes[10], INF]:
    return xs
    """,
        """
@internal
def _g(xs: DynArray[Bytes[10], INF]) -> uint256:
    return len(xs)

@external
def f(xs: DynArray[Bytes[512], 5]) -> uint256:
    return self._g(xs)
    """,
        """
@external
def f(xs: DynArray[DynArray[uint256, 4], 3]) -> DynArray[DynArray[uint256, 2], INF]:
    return xs
    """,
        # structs are nominal: a struct with a wider member is a different type
        """
struct Narrow:
    b: Bytes[8]

struct Wide:
    b: Bytes[256]

@external
def f(xs: DynArray[Narrow, 3]) -> DynArray[Wide, INF]:
    return xs
    """,
        """
struct Narrow:
    b: Bytes[8]

struct Wide:
    b: Bytes[256]

@external
def f(xs: DynArray[Narrow, 3]) -> DynArray[Wide, INF]:
    ys: DynArray[Wide, INF] = xs
    return ys
    """,
    ],
)
def test_element_narrowing_and_struct_widening_rejected(code):
    with pytest.raises(TypeMismatch):
        compile_code(code, settings=Settings(experimental_codegen=True))
