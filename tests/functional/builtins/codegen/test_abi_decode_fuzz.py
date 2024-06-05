import hypothesis.strategies as st
import pytest
from eth.codecs import abi
from hypothesis import given

from vyper.codegen.core import calculate_type_for_external_return
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

from .abi_decode import DecodeError, spec_decode

pytestmark = pytest.mark.fuzzing


possible_types = [t for t in _get_primitive_types().values() if t != HashMapT and t != DecimalT()]

possible_types_no_nesting = [t for t in possible_types if t not in _get_sequence_types().values()]


@st.composite
# max dynarray nesting
def vyper_type(draw, nesting=3):
    if nesting == 0:
        t = draw(st.sampled_from(possible_types_no_nesting))
    else:
        t = draw(st.sampled_from(possible_types))

    def _go():
        return draw(vyper_type(nesting=nesting - 1))

    if t in (BytesT, StringT):
        # arbitrary max_value
        bound = draw(st.integers(min_value=1, max_value=1024))
        return t(bound)

    if t in (DArrayT, SArrayT):
        subtype = _go()
        bound = draw(st.integers(min_value=1, max_value=128))
        return t(subtype, bound)

    if t == TupleT:
        # zero-length tuples are not allowed in vyper
        n = draw(st.integers(min_value=1, max_value=16))
        subtypes = [_go() for _ in range(n)]
        return TupleT(subtypes)

    assert isinstance(t, VyperType)
    return t


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
        # full character range, don't care if valid unicode
        characters = st.characters()

        return draw(st.text(alphabet=characters, max_size=typ.length))

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


@st.composite
def _mutate(draw, payload, max_mutations=5):
    if len(payload) == 0:
        return

    n_mutations = draw(st.integers(min_value=0, max_value=max_mutations))

    # we do point mutations, add/edit/delete up to max_mutations.

    # for add/edit, the new byte is any character, but we bias it towards
    # bytes already in the payload.
    any_byte = st.integers(min_value=0, max_value=255)
    existing_byte = st.sampled_from(list(payload))
    byte = st.one_of(existing_byte, any_byte)

    ret = bytearray(payload)

    for _ in range(n_mutations):
        if len(ret) == 0:
            # bail out. could we maybe be smarter, like only add here?
            break

        # add, edit, delete
        action = draw(st.sampled_from(["a", "e", "d"]))

        # for the mutation position, we can use any index in the payload,
        # but we bias it towards indices of nonzero bytes.
        any_ix = st.integers(min_value=0, max_value=len(ret) - 1)
        nonzero_indexes = [i for i, s in enumerate(ret) if s != 0]
        if len(nonzero_indexes) > 0:
            nonzero_ix = st.sampled_from(nonzero_indexes)
            ix = draw(st.one_of(any_ix, nonzero_ix))
        else:
            ix = draw(any_ix)

        if action == "a":
            ret.insert(ix, draw(byte))
        elif action == "e":
            ret[ix] = draw(byte)
        elif action == "d":
            ret.pop(ix)
        else:
            raise RuntimeError("unreachable")

    return bytes(ret)


@st.composite
def payload_from(draw, typ):
    wrapped_type = calculate_type_for_external_return(typ)
    data = draw(data_for_type(wrapped_type))
    schema = wrapped_type.abi_type.selector_name()
    payload = abi.encode(schema, data)

    return draw(_mutate(payload))


@given(typ=vyper_type())
def test_abi_decode_fuzz(typ, get_contract, tx_failed):
    wrapped_type = calculate_type_for_external_return(typ)
    bound = wrapped_type.abi_type.size_bound()
    type_str = repr(typ)  # annotation in vyper code
    code = f"""
@external
def run(xs: Bytes[{bound}]) -> {type_str}:
    ret: {type_str} = _abi_decode(xs, {type_str})
    return ret
    """
    c = get_contract(code)

    @given(data=payload_from(typ))
    def _fuzz(data):
        try:
            expected = spec_decode(typ, data)
            assert expected == c.run(data)
        except DecodeError:
            with tx_failed():
                c.run(data)

    _fuzz()
