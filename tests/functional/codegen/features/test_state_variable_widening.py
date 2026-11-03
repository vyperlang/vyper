import pytest

SHORT = [b"a", b"0123456789", b""]
NESTED = [[1, 2], [], [3]]
NESTED_BYTES = [[b"a", b"0123456789"], [], [b"z", b"q"]]


def test_storage_dynarray_bytes_widening(get_contract):
    """
    A `DynArray[Bytes[10], 5]` storage variable read into a
    `DynArray[Bytes[512], 5]` local, return value or argument used to be
    copied with the wide element layout, walking past the variable's slots
    and returning garbage.
    """
    code = """
stored: DynArray[Bytes[10], 5]

@internal
def _identity(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[512], 5]:
    return xs

@external
def store(xs: DynArray[Bytes[10], 5]):
    self.stored = xs

@external
def via_local() -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = self.stored
    return ys

@external
def via_return() -> DynArray[Bytes[512], 5]:
    return self.stored

@external
def via_call() -> DynArray[Bytes[512], 5]:
    return self._identity(self.stored)
    """
    c = get_contract(code)
    c.store(SHORT)
    assert c.via_local() == SHORT
    assert c.via_return() == SHORT
    assert c.via_call() == SHORT


def test_storage_nested_dynarray_widening(get_contract):
    code = """
stored: DynArray[DynArray[uint256, 2], 3]

@internal
def _identity(xs: DynArray[DynArray[uint256, 4], 3]) -> DynArray[DynArray[uint256, 4], 3]:
    return xs

@external
def store(xs: DynArray[DynArray[uint256, 2], 3]):
    self.stored = xs

@external
def via_local() -> DynArray[DynArray[uint256, 4], 3]:
    ys: DynArray[DynArray[uint256, 4], 3] = self.stored
    return ys

@external
def via_return() -> DynArray[DynArray[uint256, 4], 3]:
    return self.stored

@external
def via_call() -> DynArray[DynArray[uint256, 4], 3]:
    return self._identity(self.stored)
    """
    c = get_contract(code)
    c.store(NESTED)
    assert c.via_local() == NESTED
    assert c.via_return() == NESTED
    assert c.via_call() == NESTED


def test_storage_tuple_member_widening(get_contract):
    code = """
n: uint256
stored: DynArray[Bytes[10], 3]

@internal
def _pair() -> (uint256, DynArray[Bytes[512], 3]):
    return self.n, self.stored

@external
def store(n: uint256, xs: DynArray[Bytes[10], 3]):
    self.n = n
    self.stored = xs

@external
def via_local() -> (uint256, DynArray[Bytes[512], 3]):
    t: (uint256, DynArray[Bytes[512], 3]) = (self.n, self.stored)
    return t

@external
def via_return() -> (uint256, DynArray[Bytes[512], 3]):
    return self.n, self.stored

@external
def via_call() -> (uint256, DynArray[Bytes[512], 3]):
    return self._pair()
    """
    c = get_contract(code)
    c.store(7, SHORT)
    assert c.via_local() == (7, SHORT)
    assert c.via_return() == (7, SHORT)
    assert c.via_call() == (7, SHORT)


def test_storage_to_storage_widening(get_contract):
    code = """
narrow: DynArray[Bytes[10], 3]
wide: DynArray[Bytes[512], 3]

@external
def store(xs: DynArray[Bytes[10], 3]):
    self.narrow = xs

@external
def widen():
    self.wide = self.narrow

@external
def get_wide() -> DynArray[Bytes[512], 3]:
    return self.wide
    """
    c = get_contract(code)
    c.store(SHORT)
    c.widen()
    assert c.get_wide() == SHORT


def test_storage_to_unbounded_local(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")
    code = """
arr: DynArray[uint256, 3]

@external
def store(xs: DynArray[uint256, 3]):
    self.arr = xs

@external
def via_local() -> DynArray[uint256, INF]:
    ys: DynArray[uint256, INF] = self.arr
    return ys
    """
    c = get_contract(code)
    c.store([1, 2, 3])
    assert c.via_local() == [1, 2, 3]


@pytest.mark.requires_evm_version("cancun")
def test_transient_dynarray_bytes_widening(get_contract):
    code = """
stored: transient(DynArray[Bytes[10], 5])

@internal
def _identity(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[512], 5]:
    return xs

@external
def via_local(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], 5]:
    self.stored = xs
    ys: DynArray[Bytes[512], 5] = self.stored
    return ys

@external
def via_return(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], 5]:
    self.stored = xs
    return self.stored

@external
def via_call(xs: DynArray[Bytes[10], 5]) -> DynArray[Bytes[512], 5]:
    self.stored = xs
    return self._identity(self.stored)
    """
    c = get_contract(code)
    assert c.via_local(SHORT) == SHORT
    assert c.via_return(SHORT) == SHORT
    assert c.via_call(SHORT) == SHORT


def test_immutable_dynarray_bytes_widening(get_contract):
    """
    Immutables are copied from the data section with the size of the wide
    type, so the same widening bug reads past the immutable and skews the
    element layout.
    """
    code = """
X: immutable(DynArray[Bytes[10], 5])

@deploy
def __init__(xs: DynArray[Bytes[10], 5]):
    self.X = xs

@internal
def _identity(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[512], 5]:
    return xs

@external
def via_local() -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = self.X
    return ys

@external
def via_return() -> DynArray[Bytes[512], 5]:
    return self.X

@external
def via_call() -> DynArray[Bytes[512], 5]:
    return self._identity(self.X)

@external
def via_bare_name() -> DynArray[Bytes[512], 5]:
    # `X` is a deprecated spelling of `self.X` that is lowered by a different
    # code path; this pins that path
    return X
    """
    c = get_contract(code, SHORT)
    assert c.via_local() == SHORT
    assert c.via_return() == SHORT
    assert c.via_call() == SHORT
    assert c.via_bare_name() == SHORT


def test_immutable_nested_dynarray_widening(get_contract):
    code = """
X: immutable(DynArray[DynArray[uint256, 2], 3])

@deploy
def __init__(xs: DynArray[DynArray[uint256, 2], 3]):
    self.X = xs

@internal
def _identity(xs: DynArray[DynArray[uint256, 4], 3]) -> DynArray[DynArray[uint256, 4], 3]:
    return xs

@external
def via_local() -> DynArray[DynArray[uint256, 4], 3]:
    ys: DynArray[DynArray[uint256, 4], 3] = self.X
    return ys

@external
def via_return() -> DynArray[DynArray[uint256, 4], 3]:
    return self.X

@external
def via_call() -> DynArray[DynArray[uint256, 4], 3]:
    return self._identity(self.X)
    """
    c = get_contract(code, NESTED)
    assert c.via_local() == NESTED
    assert c.via_return() == NESTED
    assert c.via_call() == NESTED


def test_module_variable_widening(get_contract, make_input_bundle):
    lib = """
X: immutable(DynArray[Bytes[10], 5])
stored: DynArray[Bytes[10], 5]

@deploy
def __init__(xs: DynArray[Bytes[10], 5]):
    self.X = xs
    self.stored = xs
    """
    code = """
import lib

initializes: lib

@deploy
def __init__(xs: DynArray[Bytes[10], 5]):
    lib.__init__(xs)

@internal
def _identity(xs: DynArray[Bytes[512], 5]) -> DynArray[Bytes[512], 5]:
    return xs

@external
def immutable_via_local() -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = lib.X
    return ys

@external
def immutable_via_return() -> DynArray[Bytes[512], 5]:
    return lib.X

@external
def immutable_via_call() -> DynArray[Bytes[512], 5]:
    return self._identity(lib.X)

@external
def storage_via_local() -> DynArray[Bytes[512], 5]:
    ys: DynArray[Bytes[512], 5] = lib.stored
    return ys

@external
def storage_via_return() -> DynArray[Bytes[512], 5]:
    return lib.stored

@external
def storage_via_call() -> DynArray[Bytes[512], 5]:
    return self._identity(lib.stored)
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    c = get_contract(code, SHORT, input_bundle=input_bundle)
    assert c.immutable_via_local() == SHORT
    assert c.immutable_via_return() == SHORT
    assert c.immutable_via_call() == SHORT
    assert c.storage_via_local() == SHORT
    assert c.storage_via_return() == SHORT
    assert c.storage_via_call() == SHORT


def test_storage_iteration_element_widening(get_contract):
    """
    A `for` loop over a non-memory array copies each element with the element
    type's strides, but the loop body reads the loop variable with the
    annotated (wider) type, so every member past the first came back empty.
    `last_row_tail` also pins later iterations, not just the first.
    """
    code = """
stored: DynArray[DynArray[Bytes[10], 2], 3]

@external
def store(xs: DynArray[DynArray[Bytes[10], 2], 3]):
    self.stored = xs

@external
def first_row() -> (uint256, Bytes[512], Bytes[512]):
    for x: DynArray[Bytes[512], 2] in self.stored:
        return len(x), x[0], x[1]
    return 0, b"", b""

@external
def last_row_tail() -> Bytes[512]:
    out: Bytes[512] = b""
    for x: DynArray[Bytes[512], 2] in self.stored:
        if len(x) == 2:
            out = x[1]
    return out
    """
    c = get_contract(code)
    c.store(NESTED_BYTES)
    assert c.first_row() == (2, b"a", b"0123456789")
    assert c.last_row_tail() == b"q"


def test_storage_iteration_element_widening_overlapping_strides(get_contract):
    """
    With `Bytes[64]` elements read as `Bytes[96]`, the wide stride lands a
    length word where the body expects data, so the element copy ran off a
    garbage length and exhausted the gas.
    """
    code = """
stored: DynArray[DynArray[Bytes[64], 2], 3]

@external
def store(xs: DynArray[DynArray[Bytes[64], 2], 3]):
    self.stored = xs

@external
def tail() -> Bytes[96]:
    for x: DynArray[Bytes[96], 2] in self.stored:
        return x[1]
    return b""
    """
    c = get_contract(code)
    c.store([[b"one", b"twotwo"]])
    assert c.tail() == b"twotwo"


@pytest.mark.requires_evm_version("cancun")
def test_transient_iteration_element_widening(get_contract):
    code = """
stored: transient(DynArray[DynArray[Bytes[10], 2], 3])

@external
def first_row(xs: DynArray[DynArray[Bytes[10], 2], 3]) -> (uint256, Bytes[512], Bytes[512]):
    self.stored = xs
    for x: DynArray[Bytes[512], 2] in self.stored:
        return len(x), x[0], x[1]
    return 0, b"", b""
    """
    c = get_contract(code)
    assert c.first_row(NESTED_BYTES) == (2, b"a", b"0123456789")


def test_immutable_iteration_element_widening(get_contract):
    code = """
X: immutable(DynArray[DynArray[Bytes[10], 2], 3])

@deploy
def __init__(xs: DynArray[DynArray[Bytes[10], 2], 3]):
    self.X = xs

@external
def first_row() -> (uint256, Bytes[512], Bytes[512]):
    for x: DynArray[Bytes[512], 2] in self.X:
        return len(x), x[0], x[1]
    return 0, b"", b""
    """
    c = get_contract(code, NESTED_BYTES)
    assert c.first_row() == (2, b"a", b"0123456789")


def test_storage_bytes_widening_writes_only_source_words(env, get_contract):
    """
    A `Bytes[10]` value stored into a `Bytes[100]` variable used to be
    written with the destination's 5 words, reading past the 64-byte source
    buffer and writing those bytes into the variable's unused slots. Only
    the words holding the value are written.
    """
    code = """
s: Bytes[100]

@external
def set_long(x: Bytes[100]):
    self.s = x

@external
def set_short(x: Bytes[10]):
    self.s = x

@external
def get() -> Bytes[100]:
    return self.s
    """
    c = get_contract(code)
    c.set_long(b"x" * 100)
    stale = [env.get_storage(c.address, slot) for slot in range(5)]

    c.set_short(b"ab")
    assert c.get() == b"ab"
    # the length word and the one data word of the value are written; the
    # slots past them keep the earlier value, as with any shorter write
    assert env.get_storage(c.address, 0) == 2
    assert env.get_storage(c.address, 1) == int.from_bytes(b"ab".ljust(32, b"\0"))
    for slot in range(2, 5):
        assert env.get_storage(c.address, slot) == stale[slot]


def test_storage_bytes_writes_only_value_words(env, get_contract):
    # the buffer of `x` still holds `a` past the end of the shorter value;
    # none of it is written to storage
    code = """
s: Bytes[256]

@external
def f(a: Bytes[256], b: Bytes[256]):
    x: Bytes[256] = a
    x = b
    self.s = x
    """
    c = get_contract(code)
    c.f(b"\xff" * 256, b"")
    assert [env.get_storage(c.address, slot) for slot in range(9)] == [0] * 9

    c.f(b"\xff" * 256, b"ab")
    assert env.get_storage(c.address, 0) == 2
    # the rest of the data word may keep `a`'s bytes (the legacy pipeline
    # copies `b` by its length); it is not part of the value
    assert env.get_storage(c.address, 1) >> 240 == int.from_bytes(b"ab", "big")
    assert [env.get_storage(c.address, slot) for slot in range(2, 9)] == [0] * 7


def _immutable_words(env, c, size):
    # the immutables are the last bytes of the deployed code
    section = env.get_code(c.address)[-size:]
    return [int.from_bytes(section[i : i + 32], "big") for i in range(0, size, 32)]


def test_immutable_bytes_widening(env, get_contract):
    # immutables are written with the source's words: one word for an
    # empty literal, two for a `Bytes[10]`; the rest stay zero
    code = """
A: immutable(Bytes[100])
B: immutable(String[100])

@deploy
def __init__(x: Bytes[10]):
    self.A = x
    self.B = ""

@external
def get() -> (Bytes[100], String[100]):
    return self.A, self.B
    """
    c = get_contract(code, b"ab")
    assert c.get() == (b"ab", "")
    ab = int.from_bytes(b"ab".ljust(32, b"\0"), "big")
    assert _immutable_words(env, c, 320) == [2, ab] + [0] * 8


@pytest.mark.parametrize("value", ["x if c else y", "convert(s, Bytes[100])"])
def test_immutable_bytes_from_narrower_buffer(env, get_contract, value):
    # the value is typed `Bytes[100]` but its buffer is narrower; nothing
    # past the buffer is written to the immutable
    code = f"""
A: immutable(Bytes[100])
t: Bytes[100]

@deploy
def __init__(c: bool, x: Bytes[10], y: Bytes[100], s: String[10]):
    self.A = {value}
    self.t = y

@external
def get() -> Bytes[100]:
    return self.A
    """
    c = get_contract(code, True, b"ab", b"\xff" * 100, "ab")
    assert c.get() == b"ab"
    ab = int.from_bytes(b"ab".ljust(32, b"\0"), "big")
    assert _immutable_words(env, c, 160) == [2, ab, 0, 0, 0]


def test_immutable_bytes_from_tuple_member(env, get_contract, experimental_codegen):
    # a bounded member of a tuple with an unbounded member is packed by its
    # length, so the next member follows its value directly
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")
    code = """
A: immutable(Bytes[100])

@internal
def _pair() -> (Bytes[100], Bytes[INF]):
    return b"ab", b"hello"

@deploy
def __init__():
    self.A = self._pair()[0]

@external
def get() -> Bytes[100]:
    return self.A
    """
    c = get_contract(code)
    assert c.get() == b"ab"
    ab = int.from_bytes(b"ab".ljust(32, b"\0"), "big")
    assert _immutable_words(env, c, 160) == [2, ab, 0, 0, 0]


def test_immutable_bytes_writes_only_value_words(env, get_contract):
    # the buffer of `x` still holds `a` past the end of the shorter value;
    # none of it is written to the immutable
    code = """
A: immutable(Bytes[256])

@deploy
def __init__(a: Bytes[256], b: Bytes[256]):
    x: Bytes[256] = a
    x = b
    self.A = x

@external
def get() -> Bytes[256]:
    return self.A
    """
    c = get_contract(code, b"\xff" * 256, b"")
    assert c.get() == b""
    assert _immutable_words(env, c, 288) == [0] * 9


@pytest.mark.parametrize("location", ["", "transient"])
def test_short_bytes_store_overwrites_data_word(get_contract, location):
    # a bytestring of at most 32 bytes is written with both its words, as
    # in the legacy pipeline, so emptying it leaves no stale data word for
    # a signed convert to read as the sign
    typ = f"{location}(Bytes[32])" if location else "Bytes[32]"
    code = f"""
s: {typ}

@external
def f(y: Bytes[32]) -> (int256, int8):
    self.s = b"\\x80"
    self.s = y
    return convert(self.s, int256), convert(self.s, int8)
    """
    c = get_contract(code)
    assert c.f(b"") == (0, 0)


def test_short_bytes_immutable_overwrites_data_word(get_contract):
    code = """
B: immutable(Bytes[32])

@deploy
def __init__(z: Bytes[32]):
    for i: uint256 in range(2):
        self.B = b"\\x80" if i == 0 else z

@external
def get() -> int256:
    return convert(self.B, int256)
    """
    c = get_contract(code, b"")
    assert c.get() == 0
