"""
Writing a value that contains a DynArray or a bytestring to storage or
transient storage writes only the words that hold it: each DynArray's
length and live elements, each bytestring's length and data words. The
slots past them keep their earlier contents.

Each case stores `old`, then a shorter value through a local whose buffer
still holds `junk` past the shorter value's end. A copy of the whole
buffer would write `junk`'s words into the slots; they must keep `old`'s.
"""

import pytest

from vyper import compile_code
from vyper.evm.opcodes import version_check

AB = int.from_bytes(b"ab".ljust(32, b"\0"), "big")
X = int.from_bytes(b"x" * 32, "big")
X8 = int.from_bytes(b"x" * 8 + b"\0" * 24, "big")

STRUCTS = """
struct A:
    a: DynArray[uint256, 3]
    b: uint256

struct B:
    s: String[64]
    b: uint256

struct C:
    inner: A
    c: DynArray[uint256, 2]

struct D:
    a: DynArray[uint256, 2]
    s: uint256[3]
    t: String[40]

struct E:
    b: Bytes[16]
    c: uint256
"""

# (type, old, junk, new, slots after storing new over old)
CASES = [
    ("A", ([1, 2, 3], 4), ([7, 8, 9], 7), ([5], 6), [1, 5, 2, 3, 6]),
    ("B", ("x" * 64, 7), ("y" * 64, 7), ("ab", 8), [2, AB, X, 8]),
    (
        "C",
        (([1, 2, 3], 4), [5, 6]),
        (([7, 7, 7], 7), [7, 7]),
        (([8], 9), []),
        [1, 8, 2, 3, 9, 0, 5, 6],
    ),
    (
        "D",
        ([1, 2], [3, 4, 5], "x" * 40),
        ([7, 7], [7, 7, 7], "y" * 40),
        ([6], [8, 9, 10], "ab"),
        [1, 6, 2, 8, 9, 10, 2, AB, X8],
    ),
    ("DynArray[uint256, 2][2]", [[1, 2], [3, 4]], [[7, 7], [7, 7]], [[5], []], [1, 5, 2, 0, 3, 4]),
    (
        "DynArray[DynArray[uint256, 2], 2]",
        [[1, 2], [3, 4]],
        [[7, 7], [7, 7]],
        [[5]],
        [1, 1, 5, 2, 2, 3, 4],
    ),
    (
        "(Bytes[64], DynArray[uint256, 2])",
        (b"x" * 64, [1, 2]),
        (b"y" * 64, [7, 7]),
        (b"ab", [3]),
        [2, AB, X, 1, 3, 2],
    ),
    (
        "DynArray[String[64], 2]",
        ["x" * 64, "x" * 64],
        ["y" * 64, "y" * 64],
        ["ab"],
        [1, 2, AB, X, 64, X, X],
    ),
    (
        "DynArray[A, 2]",
        [([1, 2, 3], 4), ([5, 6, 7], 8)],
        [([7, 7, 7], 7), ([7, 7, 7], 7)],
        [([9], 10)],
        [1, 1, 9, 2, 3, 10, 3, 5, 6, 7, 8],
    ),
]

# an empty bytestring writes only its length word. legacy codegen also
# copies the data word when the source type's maximum length is at most
# 32, so these cases hold only under venom
EMPTY_BYTESTRING_CASES = [
    ("E", (b"ab", 2), (b"y" * 16, 7), (b"", 4), [0, AB, 4]),
    ("String[32]", "ab", "y" * 32, "", [0, AB]),
]


def _first_slot():
    # before cancun, slot 0 holds the reentrancy lock
    return 0 if version_check(begin="cancun") else 1


def _check_storage_write(env, get_contract, typ, old, junk, new, expected):
    code = f"""
{STRUCTS}

s: {typ}

@external
def set(junk: {typ}, new: {typ}):
    x: {typ} = junk
    x = new
    self.s = x

@external
def get() -> {typ}:
    return self.s
    """
    c = get_contract(code)
    c.set(old, old)
    c.set(junk, new)
    assert c.get() == new
    base = _first_slot()
    assert [env.get_storage(c.address, base + i) for i in range(len(expected))] == expected


@pytest.mark.parametrize("typ,old,junk,new,expected", CASES)
def test_storage_write_keeps_dead_slots(env, get_contract, typ, old, junk, new, expected):
    _check_storage_write(env, get_contract, typ, old, junk, new, expected)


@pytest.mark.parametrize("typ,old,junk,new,expected", EMPTY_BYTESTRING_CASES)
def test_storage_write_of_empty_bytestring_keeps_data_word(
    env, get_contract, experimental_codegen, typ, old, junk, new, expected
):
    if not experimental_codegen:
        pytest.skip("legacy codegen writes the data word of an empty short bytestring")
    _check_storage_write(env, get_contract, typ, old, junk, new, expected)


def test_storage_append_keeps_dead_slots(env, get_contract):
    # appending an element with a DynArray member writes only its live slots
    code = f"""
{STRUCTS}

s: DynArray[A, 2]

@external
def push(junk: A, new: A):
    x: A = junk
    x = new
    self.s.append(x)

@external
def pop():
    self.s.pop()
    """
    c = get_contract(code)
    c.push(([1, 2, 3], 4), ([1, 2, 3], 4))
    c.pop()
    c.push(([7, 8, 9], 7), ([5], 6))
    base = _first_slot()
    assert [env.get_storage(c.address, base + i) for i in range(6)] == [1, 1, 5, 2, 3, 6]


def _check_transient_write(get_contract, typ, old, junk, new, expected):
    # transient storage can't be read from outside, so the contract reads
    # its own slots through a delegatecall to `reader`, whose first transient
    # variable lies at the same slot as `t`
    n = len(expected)
    reader = get_contract(f"""
t: transient(uint256[{n}])

@external
def words() -> uint256[{n}]:
    return self.t
    """)
    code = f"""
{STRUCTS}

t: transient({typ})

@external
def run(reader: address, old: {typ}, junk: {typ}, new: {typ}) -> ({typ}, uint256[{n}]):
    self.t = old
    x: {typ} = junk
    x = new
    self.t = x
    res: Bytes[{32 * n}] = raw_call(
        reader, method_id("words()"), max_outsize={32 * n}, is_delegate_call=True
    )
    return self.t, abi_decode(res, uint256[{n}])
    """
    c = get_contract(code)
    assert c.run(reader.address, old, junk, new) == (new, expected)


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("typ,old,junk,new,expected", CASES)
def test_transient_write_keeps_dead_slots(get_contract, typ, old, junk, new, expected):
    _check_transient_write(get_contract, typ, old, junk, new, expected)


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("typ,old,junk,new,expected", EMPTY_BYTESTRING_CASES)
def test_transient_write_of_empty_bytestring_keeps_data_word(
    get_contract, experimental_codegen, typ, old, junk, new, expected
):
    if not experimental_codegen:
        pytest.skip("legacy codegen writes the data word of an empty short bytestring")
    _check_transient_write(get_contract, typ, old, junk, new, expected)


STORAGE_SPACES = [
    "{}",
    pytest.param("transient({})", marks=pytest.mark.requires_evm_version("cancun")),
]

CLEAR_STRUCTS = """
struct J:
    a: DynArray[uint256, 2]
    b: uint256
    c: uint256[4]
    d: uint256
"""

# (type, words before the clear, words after it). assigning empty(T) writes
# zero to every static word and every length word, and nothing else
CLEAR_CASES = [
    ("uint256[5]", [*range(1, 6)], [0] * 5),
    ("uint256[6]", [*range(1, 7)], [0] * 6),
    ("uint256[7]", [*range(1, 8)], [0] * 7),
    (
        "(J[2], Bytes[32], uint256[8])",
        [2, *range(1, 9), 2, *range(9, 17), 2, AB, *range(17, 25)],
        [0, 1, 2] + [0] * 6 + [0, 9, 10] + [0] * 6 + [0, AB] + [0] * 8,
    ),
    (
        "(uint256[7], DynArray[uint256, 2], uint256[6], String[32], uint256[5])",
        [*range(1, 8), 2, 8, 9, *range(10, 16), 2, AB, *range(16, 21)],
        [0] * 7 + [0, 8, 9] + [0] * 6 + [0, AB] + [0] * 5,
    ),
]


@pytest.mark.parametrize("declaration", STORAGE_SPACES)
@pytest.mark.parametrize("typ,initial,expected", CLEAR_CASES)
def test_clear_keeps_dead_slots(get_contract, declaration, typ, initial, expected):
    clearer = get_contract(f"""
{CLEAR_STRUCTS}

before: {declaration.format("uint256")}
s: {declaration.format(typ)}
after: {declaration.format("uint256")}

@external
def clear():
    self.s = empty({typ})
    """)
    # `clear` runs through a delegatecall, over `words`: its first and last
    # words lie at the slots of `before` and `after` and must survive
    initial = [101, *initial, 102]
    expected = [101, *expected, 102]
    words = f"uint256[{len(initial)}]"
    probe = get_contract(f"""
words: {declaration.format(words)}

@external
def run(clearer: address, initial: {words}) -> {words}:
    self.words = initial
    raw_call(clearer, method_id("clear()"), is_delegate_call=True)
    return self.words
    """)
    assert probe.run(clearer.address, initial) == expected


@pytest.mark.parametrize("declaration", STORAGE_SPACES)
def test_clear_reads_no_memory(compiler_settings, declaration):
    if not compiler_settings.experimental_codegen:
        pytest.skip("checks how venom lowers the clear")

    source = f"""
struct S:
    words: uint256[32]
    items: DynArray[uint256, 4]

s: {declaration.format("S")}

@external
def clear():
    self.s = empty(S)
    """
    out = compile_code(source, settings=compiler_settings, output_formats=["opcodes_runtime"])
    opcodes = out["opcodes_runtime"].split()
    store = "TSTORE" if "transient" in declaration else "SSTORE"
    # one store in the loop over `words`, one for the length of `items`
    assert opcodes.count(store) == 2
    assert "MLOAD" not in opcodes
