from dataclasses import dataclass

import hypothesis as hp
import hypothesis.strategies as st
import pytest
from eth.codecs import abi

from tests.evm_backends.base_env import EvmError
from vyper.codegen.core import calculate_type_for_external_return, needs_external_call_wrap
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DArrayT,
    DecimalT,
    HashMapT,
    IntegerT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
    VyperType,
    _get_primitive_types,
    _get_sequence_types,
)

from .abi_decode import DecodeError, spec_decode

pytestmark = pytest.mark.fuzzing

type_ctors = []
for t in _get_primitive_types().values():
    if t == HashMapT or t == DecimalT():
        continue
    if isinstance(t, VyperType):
        t = t.__class__
    if t in type_ctors:
        continue
    type_ctors.append(t)

complex_static_ctors = [SArrayT, TupleT, StructT]
complex_dynamic_ctors = [DArrayT]
leaf_ctors = [t for t in type_ctors if t not in _get_sequence_types().values()]
static_leaf_ctors = [t for t in leaf_ctors if t._is_prim_word]
dynamic_leaf_ctors = [BytesT, StringT]

MAX_MUTATIONS = 33


@st.composite
# max type nesting
def vyper_type(draw, nesting=3, skip=None, source_fragments=None):
    assert nesting >= 0

    skip = skip or []
    if source_fragments is None:
        source_fragments = []

    st_leaves = st.one_of(st.sampled_from(dynamic_leaf_ctors), st.sampled_from(static_leaf_ctors))
    st_complex = st.one_of(
        st.sampled_from(complex_dynamic_ctors), st.sampled_from(complex_static_ctors)
    )

    if nesting == 0:
        st_type = st_leaves
    else:
        st_type = st.one_of(st_complex, st_leaves)

    # filter here is a bit of a kludge, would be better to improve sampling
    t = draw(st_type.filter(lambda t: t not in skip))

    # note: maybe st.deferred is good here, we could define it with
    # mutual recursion
    def _go(skip=skip):
        _, typ = draw(vyper_type(nesting=nesting - 1, skip=skip, source_fragments=source_fragments))
        return typ

    def finalize(typ):
        return source_fragments, typ

    if t in (BytesT, StringT):
        # arbitrary max_value
        bound = draw(st.integers(min_value=1, max_value=1024))
        return finalize(t(bound))

    if t == SArrayT:
        subtype = _go(skip=[TupleT, BytesT, StringT])
        bound = draw(st.integers(min_value=1, max_value=6))
        return finalize(t(subtype, bound))
    if t == DArrayT:
        subtype = _go(skip=[TupleT])
        bound = draw(st.integers(min_value=1, max_value=16))
        return finalize(t(subtype, bound))

    if t == TupleT:
        # zero-length tuples are not allowed in vyper
        n = draw(st.integers(min_value=1, max_value=6))
        subtypes = [_go() for _ in range(n)]
        return finalize(TupleT(subtypes))

    if t == StructT:
        n = draw(st.integers(min_value=1, max_value=6))
        subtypes = {f"x{i}": _go() for i in range(n)}
        _id = len(source_fragments)  # poor man's unique id
        name = f"MyStruct{_id}"
        typ = StructT(name, subtypes)
        source_fragments.append(typ.def_source_str())
        return finalize(StructT(name, subtypes))

    if t in (BoolT, AddressT):
        return finalize(t())

    if t == IntegerT:
        signed = draw(st.booleans())
        bits = 8 * draw(st.integers(min_value=1, max_value=32))
        return finalize(t(signed, bits))

    if t == BytesM_T:
        m = draw(st.integers(min_value=1, max_value=32))
        return finalize(t(m))

    raise RuntimeError("unreachable")


@st.composite
def data_for_type(draw, typ):
    def _go(t):
        return draw(data_for_type(t))

    if isinstance(typ, TupleT):
        return tuple(_go(item_t) for item_t in typ.member_types)

    if isinstance(typ, StructT):
        return tuple(_go(item_t) for item_t in typ.tuple_members())

    if isinstance(typ, SArrayT):
        return [_go(typ.value_type) for _ in range(typ.length)]

    if isinstance(typ, DArrayT):
        n = draw(st.integers(min_value=0, max_value=typ.length))
        return [_go(typ.value_type) for _ in range(n)]

    if isinstance(typ, StringT):
        # technically the ABI spec doesn't say string has to be valid utf-8,
        # but eth-stdlib won't encode invalid utf-8
        return draw(st.text(max_size=typ.length))

    if isinstance(typ, BytesT):
        return draw(st.binary(max_size=typ.length))

    if isinstance(typ, IntegerT):
        lo, hi = typ.ast_bounds
        return draw(st.integers(min_value=lo, max_value=hi))

    if isinstance(typ, BytesM_T):
        return draw(st.binary(min_size=typ.length, max_size=typ.length))

    if isinstance(typ, BoolT):
        return draw(st.booleans())

    if isinstance(typ, AddressT):
        ret = draw(st.binary(min_size=20, max_size=20))
        return "0x" + ret.hex()

    raise RuntimeError("unreachable")


def _sort2(x, y):
    if x > y:
        return y, x
    return x, y


@st.composite
def _mutate(draw, payload, max_mutations=MAX_MUTATIONS):
    # do point+bulk mutations,
    # add/edit/delete/splice/flip up to max_mutations.
    if len(payload) == 0:
        return

    ret = bytearray(payload)

    # for add/edit, the new byte is any character, but we bias it towards
    # bytes already in the payload.
    st_any_byte = st.integers(min_value=0, max_value=255)
    payload_nonzeroes = list(x for x in payload if x != 0)
    if len(payload_nonzeroes) > 0:
        st_existing_byte = st.sampled_from(payload)
        st_byte = st.one_of(st_existing_byte, st_any_byte)
    else:
        st_byte = st_any_byte

    # add, edit, delete, word, splice, flip
    possible_actions = "adwww"
    actions = draw(st.lists(st.sampled_from(possible_actions), max_size=MAX_MUTATIONS))

    for action in actions:
        if len(ret) == 0:
            # bail out. could we maybe be smarter, like only add here?
            break

        # for the mutation position, we can use any index in the payload,
        # but we bias it towards indices of nonzero bytes.
        st_any_ix = st.integers(min_value=0, max_value=len(ret) - 1)
        nonzero_indexes = [i for i, s in enumerate(ret) if s != 0]
        if len(nonzero_indexes) > 0:
            st_nonzero_ix = st.sampled_from(nonzero_indexes)
            st_ix = st.one_of(st_any_ix, st_nonzero_ix)
        else:
            st_ix = st_any_ix

        ix = draw(st_ix)

        if action == "a":
            ret.insert(ix, draw(st_byte))
        elif action == "e":
            ret[ix] = draw(st_byte)
        elif action == "d":
            ret.pop(ix)
        elif action == "w":
            # splice word
            st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)

            # valid pointers, but maybe *just* out of bounds
            st_poison = st.integers(min_value=-2 * len(ret), max_value=2 * len(ret)).map(
                lambda x: x % (2**256)
            )
            word = draw(st.one_of(st_poison, st_uint256))
            ret[ix - 31 : ix + 1] = word.to_bytes(32)
        elif action == "s":
            ix2 = draw(st_ix)
            ix, ix2 = _sort2(ix, ix2)
            ix2 += 1
            # max splice is 64 bytes, due to MAX_BUFFER_SIZE limitation in st.binary
            ix2 = ix + (ix2 % 64)
            length = ix2 - ix
            substr = draw(st.binary(min_size=length, max_size=length))
            ret[ix:ix2] = substr
        elif action == "f":
            ix2 = draw(st_ix)
            ix, ix2 = _sort2(ix, ix2)
            ix2 += 1
            for i in range(ix, ix2):
                # flip the bits in the byte
                ret[i] = 255 ^ ret[i]
        else:
            raise RuntimeError("unreachable")

    return bytes(ret)


@st.composite
def payload_from(draw, typ):
    data = draw(data_for_type(typ))
    schema = typ.abi_type.selector_name()
    payload = abi.encode(schema, data)

    return draw(_mutate(payload))


_settings = dict(
    report_multiple_bugs=False,
    # verbosity=hp.Verbosity.verbose,
    suppress_health_check=(
        hp.HealthCheck.data_too_large,
        hp.HealthCheck.too_slow,
        hp.HealthCheck.large_base_example,
        hp.HealthCheck.nested_given,
    ),
    phases=(
        hp.Phase.explicit,
        hp.Phase.reuse,
        hp.Phase.generate,
        hp.Phase.target,
        # Phase.shrink,  # can force long waiting for examples
        # Phase.explain,  # not helpful here
    ),
)


@dataclass(frozen=True)
class _TypeStats:
    nesting: int = 0
    num_dynamic_types: int = 0  # number of dynamic types in the type
    breadth: int = 0  # e.g. int16[50] has higher breadth than int16[1]
    width: int = 0  # size of type


def _type_stats(typ: VyperType) -> _TypeStats:
    def _finalize():  # little trick to save re-typing the arguments
        width = typ.memory_bytes_required
        return _TypeStats(
            nesting=nesting, num_dynamic_types=num_dynamic_types, breadth=breadth, width=width
        )

    if typ._is_prim_word:
        nesting = 0
        breadth = 1
        num_dynamic_types = 0
        return _finalize()

    if isinstance(typ, (BytesT, StringT)):
        nesting = 0
        breadth = 1  # idk
        num_dynamic_types = 1
        return _finalize()

    if isinstance(typ, TupleT):
        substats = [_type_stats(t) for t in typ.member_types]
        nesting = 1 + max(s.nesting for s in substats)
        breadth = max(typ.length, *[s.breadth for s in substats])
        num_dynamic_types = sum(s.num_dynamic_types for s in substats)
        return _finalize()

    if isinstance(typ, StructT):
        substats = [_type_stats(t) for t in typ.tuple_members()]
        nesting = 1 + max(s.nesting for s in substats)
        breadth = max(len(typ.member_types), *[s.breadth for s in substats])
        num_dynamic_types = sum(s.num_dynamic_types for s in substats)
        return _finalize()

    if isinstance(typ, DArrayT):
        substat = _type_stats(typ.value_type)
        nesting = 1 + substat.nesting
        breadth = max(typ.count, substat.breadth)
        num_dynamic_types = 1 + substat.num_dynamic_types
        return _finalize()

    if isinstance(typ, SArrayT):
        substat = _type_stats(typ.value_type)
        nesting = 1 + substat.nesting
        breadth = max(typ.count, substat.breadth)
        num_dynamic_types = substat.num_dynamic_types
        return _finalize()

    raise RuntimeError("unreachable")


@pytest.fixture(scope="module")
def payload_copier(get_contract_from_ir):
    # some contract which will return the buffer passed to it
    # note: hardcode the location of the bytestring
    ir = [
        "with",
        "length",
        ["calldataload", 36],
        ["seq", ["calldatacopy", 0, 68, "length"], ["return", 0, "length"]],
    ]
    return get_contract_from_ir(["deploy", 0, ir, 0])


PARALLELISM = 1  # increase on fuzzer box


# NOTE: this is a heavy test. 100 types * 100 payloads per type can take
# 3-4minutes on a regular CPU core.
@pytest.mark.parametrize("_n", list(range(PARALLELISM)))
@hp.given(typ=vyper_type())
@hp.settings(max_examples=100, **_settings)
def test_abi_decode_fuzz(_n, typ, get_contract, tx_failed, payload_copier, env):
    source_fragments, typ = typ
    # import time
    # t0 = time.time()
    # print("ENTER", typ)

    wrapped_type = calculate_type_for_external_return(typ)

    stats = _type_stats(typ)
    # for k, v in asdict(stats).items():
    #     event(k, v)
    hp.target(stats.num_dynamic_types)
    # hp.target(typ.abi_type.is_dynamic() + typ.abi_type.is_complex_type()))

    # add max_mutations bytes worth of padding so we don't just get caught
    # by bytes length check at function entry
    type_bound = wrapped_type.abi_type.size_bound()
    buffer_bound = type_bound + MAX_MUTATIONS

    preamble = "\n\n".join(source_fragments)
    type_str = str(typ)  # annotation in vyper code

    code = f"""
{preamble}

@external
def run(xs: Bytes[{buffer_bound}]) -> {type_str}:
    ret: {type_str} = abi_decode(xs, {type_str})
    return ret

interface Foo:
    def foo(xs: Bytes[{buffer_bound}]) -> {type_str}: view  # STATICCALL
    def bar(xs: Bytes[{buffer_bound}]) -> {type_str}: nonpayable  # CALL

@external
def run2(xs: Bytes[{buffer_bound}], copier: Foo) -> {type_str}:
    assert len(xs) <= {type_bound}
    return staticcall copier.foo(xs)

@external
def run3(xs: Bytes[{buffer_bound}], copier: Foo) -> {type_str}:
    assert len(xs) <= {type_bound}
    return (extcall copier.bar(xs))
    """
    try:
        c = get_contract(code)
    except EvmError as e:
        if env.contract_size_limit_error in str(e):
            hp.assume(False)
    # print(code)
    hp.note(code)
    c = get_contract(code)

    @hp.given(data=payload_from(wrapped_type))
    @hp.settings(max_examples=100, **_settings)
    def _fuzz(data):
        hp.note(f"type: {typ}")
        hp.note(f"abi_t: {wrapped_type.abi_type.selector_name()}")
        hp.note(data.hex())

        try:
            expected = spec_decode(wrapped_type, data)

            # unwrap if necessary
            if needs_external_call_wrap(typ):
                assert isinstance(expected, tuple)
                (expected,) = expected

            hp.note(f"expected {expected}")
            assert expected == c.run(data)
            assert expected == c.run2(data, payload_copier.address)
            assert expected == c.run3(data, payload_copier.address)

        except DecodeError:
            # note EvmError includes reverts *and* exceptional halts.
            # we can get OOG during abi decoding due to how
            # `_abi_payload_size()` works
            hp.note("expect failure")
            with tx_failed(EvmError):
                c.run(data)
            with tx_failed(EvmError):
                c.run2(data, payload_copier.address)
            with tx_failed(EvmError):
                c.run3(data, payload_copier.address)

    _fuzz()

    # t1 = time.time()
    # print(f"elapsed {t1 - t0}s")


@pytest.mark.parametrize("_n", list(range(PARALLELISM)))
@hp.given(typ=vyper_type())
@hp.settings(max_examples=100, **_settings)
def test_abi_decode_no_wrap_fuzz(_n, typ, get_contract, tx_failed, env):
    source_fragments, typ = typ
    # import time
    # t0 = time.time()
    # print("ENTER", typ)

    stats = _type_stats(typ)
    hp.target(stats.num_dynamic_types)

    # add max_mutations bytes worth of padding so we don't just get caught
    # by bytes length check at function entry
    type_bound = typ.abi_type.size_bound()
    buffer_bound = type_bound + MAX_MUTATIONS

    type_str = str(typ)  # annotation in vyper code
    preamble = "\n\n".join(source_fragments)

    code = f"""
{preamble}

@external
def run(xs: Bytes[{buffer_bound}]) -> {type_str}:
    ret: {type_str} = abi_decode(xs, {type_str}, unwrap_tuple=False)
    return ret
    """
    try:
        c = get_contract(code)
    except EvmError as e:
        if env.contract_size_limit_error in str(e):
            hp.assume(False)

    @hp.given(data=payload_from(typ))
    @hp.settings(max_examples=100, **_settings)
    def _fuzz(data):
        hp.note(code)
        hp.note(data.hex())
        try:
            expected = spec_decode(typ, data)
            hp.note(f"expected {expected}")
            assert expected == c.run(data)
        except DecodeError:
            hp.note("expect failure")
            with tx_failed(EvmError):
                c.run(data)

    _fuzz()

    # t1 = time.time()
    # print(f"elapsed {t1 - t0}s")
