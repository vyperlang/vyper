import hypothesis.strategies as st
from eth.codecs import abi

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

type_ctors = []
for t in _get_primitive_types().values():
    if t == DecimalT():
        continue
    if isinstance(t, VyperType):
        t = t.__class__
    if t in type_ctors:
        continue
    type_ctors.append(t)

# TODO: add flags, decimals and interfaces when supported/needed
complex_static_ctors = [SArrayT, TupleT, StructT]
complex_dynamic_ctors = [DArrayT, HashMapT]
leaf_ctors = [t for t in type_ctors if t not in _get_sequence_types().values()]
static_leaf_ctors = [t for t in leaf_ctors if t._is_prim_word]
dynamic_leaf_ctors = [BytesT, StringT]


def create_id_generator():
    counter = 0

    def get_next_id():
        nonlocal counter
        counter += 1
        return counter

    return get_next_id


get_next_id = create_id_generator()


@st.composite
def vyper_type(draw, nesting=3, skip=None, source_fragments=None):
    """
    generates a random VyperType and source code fragments (like struct definitions).
    """
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
        subtype = _go(skip=[TupleT, BytesT, StringT, HashMapT])
        bound = draw(st.integers(min_value=1, max_value=6))
        return finalize(t(subtype, bound))

    if t == DArrayT:
        subtype = _go(skip=[TupleT, HashMapT])
        bound = draw(st.integers(min_value=1, max_value=16))
        return finalize(t(subtype, bound))

    if t == HashMapT:
        hashmap_value_skip = complex_static_ctors + complex_dynamic_ctors
        key_type = _go(skip=hashmap_value_skip)
        assert key_type._as_hashmap_key, f"{key_type} is not a valid hashmap key"
        value_type = _go()
        return finalize(t(key_type, value_type))

    if t == TupleT:
        # zero-length tuples are not allowed in vyper
        n = draw(st.integers(min_value=1, max_value=6))
        subtypes = [_go(skip=[HashMapT]) for _ in range(n)]
        return finalize(TupleT(subtypes))

    if t == StructT:
        n = draw(st.integers(min_value=1, max_value=6))
        subtypes = {f"x{i}": _go(skip=[HashMapT]) for i in range(n)}
        _id = get_next_id()
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
def data_for_type(draw, typ: VyperType):
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

    if isinstance(typ, HashMapT):
        raise NotImplementedError()

    raise RuntimeError("unreachable")


def _sort2(x, y):
    if x > y:
        return y, x
    return x, y


MAX_MUTATIONS = 33


@st.composite
def _mutate(draw, payload: bytes, max_mutations=MAX_MUTATIONS):
    # do point+bulk mutations,
    # add/edit/delete/splice/flip up to max_mutations.
    if len(payload) == 0:
        return b""

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
def payload_from(draw, typ: VyperType):
    data = draw(data_for_type(typ))
    schema = typ.abi_type.selector_name()
    payload = abi.encode(schema, data)

    return draw(_mutate(payload))
