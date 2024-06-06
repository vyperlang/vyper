import hypothesis.strategies as st
import pytest
from eth.codecs import abi
from hypothesis import HealthCheck, Phase, given, note, settings, Verbosity, example, target

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
    TupleT,
    VyperType,
    _get_primitive_types,
    _get_sequence_types,
)
from vyper.semantics.types.shortcuts import UINT256_T

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

type_ctors_no_nesting = [t for t in type_ctors if t not in _get_sequence_types().values()]

MAX_MUTATIONS = 4


@st.composite
# max dynarray nesting
def vyper_type(draw, nesting=3, skip=None):
    assert nesting >= 0

    skip = skip or []
    if nesting == 0:
        t = draw(st.sampled_from([s for s in type_ctors_no_nesting if s not in skip]))
    else:
        t = draw(st.sampled_from([s for s in type_ctors if s not in skip]))

    def _go(skip=skip):
        return draw(vyper_type(nesting=nesting - 1, skip=skip))

    if t in (BytesT, StringT):
        # arbitrary max_value
        bound = draw(st.integers(min_value=1, max_value=1024))
        return t(bound)

    if t in (DArrayT, SArrayT):
        if t == SArrayT:
            subtype = _go(skip=[TupleT, BytesT, StringT])
        else:
            subtype = _go(skip=[TupleT])
        bound = draw(st.integers(min_value=1, max_value=16))
        return t(subtype, bound)

    if t == TupleT:
        # zero-length tuples are not allowed in vyper
        n = draw(st.integers(min_value=1, max_value=6))
        subtypes = [_go() for _ in range(n)]
        return TupleT(subtypes)

    if t in (BoolT, AddressT):
        return t()

    if t == IntegerT:
        signed = draw(st.booleans())
        bits = 8 * draw(st.integers(min_value=1, max_value=32))
        return t(signed, bits)

    if t == BytesM_T:
        m = draw(st.integers(min_value=1,max_value=32))
        return t(m)

    raise RuntimeError("unreachable")


@st.composite
def data_for_type(draw, typ):
    def _go(t):
        return draw(data_for_type(t))

    if isinstance(typ, TupleT):
        return tuple(_go(item_t) for item_t in typ.member_types)

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

    # add, edit, delete, splice, flip
    actions = draw(st.lists(st.sampled_from("aedsf"), max_size=MAX_MUTATIONS))

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
    verbosity=Verbosity.verbose,
    suppress_health_check=(
        HealthCheck.data_too_large,
        HealthCheck.too_slow,
        HealthCheck.large_base_example,
    ),
    phases=(
        Phase.explicit,
        Phase.reuse,
        Phase.generate,
        Phase.target,
        # Phase.shrink,  # can force long waiting for examples
        # Phase.explain,  # not helpful here
    ),
)


@given(typ=vyper_type())
@settings(max_examples=1000, **_settings)
def test_abi_decode_fuzz(typ, get_contract, tx_failed):
    wrapped_type = calculate_type_for_external_return(typ)

    target(typ.abi_type.is_dynamic() + typ.abi_type.is_complex_type())

    # add max_mutations bytes worth of padding so we don't just get caught
    # by bytes length check at function entry
    bound = wrapped_type.abi_type.size_bound() + MAX_MUTATIONS
    type_str = repr(typ)  # annotation in vyper code
    # TODO: intrinsic decode from staticcall/extcall
    # TODO: _abi_decode from other sources (staticcall/extcall?)
    # TODO: dirty the buffer
    # TODO: check unwrap_tuple=False
    code = f"""
@external
def run(xs: Bytes[{bound}]) -> {type_str}:
    ret: {type_str} = _abi_decode(xs, {type_str})
    return ret
    """
    c = get_contract(code)

    @given(data=payload_from(wrapped_type))
    @settings(max_examples=10000, **_settings)
    def _fuzz(data):
        note(f"type: {typ}")
        note(f"abi_t: {wrapped_type.abi_type.selector_name()}")
        note(code)

        try:
            expected = spec_decode(wrapped_type, data)

            # unwrap if necessary
            if needs_external_call_wrap(typ):
                assert isinstance(expected, tuple)
                (expected,) = expected

            assert expected == c.run(data)

        except DecodeError:
            # note EvmError includes reverts *and* exceptional halts.
            # we can get OOG during abi decoding due to how
            # `_abi_payload_size()` works
            with tx_failed(EvmError):
                c.run(data)

    _fuzz()
