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

from vyper.evm.opcodes import version_check

AB = int.from_bytes(b"ab".ljust(32, b"\0"), "big")
X = int.from_bytes(b"x" * 32, "big")

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
]


def _first_slot():
    # before cancun, slot 0 holds the reentrancy lock
    return 0 if version_check(begin="cancun") else 1


@pytest.mark.parametrize("typ,old,junk,new,expected", CASES)
def test_storage_write_keeps_dead_slots(env, get_contract, typ, old, junk, new, expected):
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


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("typ,old,junk,new,expected", CASES)
def test_transient_write_keeps_dead_slots(get_contract, typ, old, junk, new, expected):
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
