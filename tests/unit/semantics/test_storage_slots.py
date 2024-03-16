import pytest

from vyper.exceptions import StorageLayoutException

code = """

struct StructOne:
    a: String[33]
    b: uint256[3]

struct StructTwo:
    a: Bytes[5]
    b: int128[2]
    c: String[64]

a: public(StructOne)
b: public(uint256[2])
c: public(Bytes[32])
d: public(int128[4])
foo: public(HashMap[uint256, uint256[3]])
dyn_array: DynArray[uint256, 3]
e: public(String[48])
f: public(int256[1])
g: public(StructTwo[2])
h: public(int256[1])


@deploy
def __init__():
    self.a = StructOne(a="ok", b=[4,5,6])
    self.b = [7, 8]
    self.c = b"thisisthirtytwobytesokhowdoyoudo"
    self.d = [-1, -2, -3, -4]
    self.e = "A realllllly long string but we won't use it all"
    self.f = [33]
    self.g = [
        StructTwo(a=b"hello", b=[-66, 420], c="another string"),
        StructTwo(
            a=b"gbye",
            b=[1337, 888],
            c="whatifthisstringtakesuptheentirelengthwouldthatbesobadidothinkso"
        )
    ]
    self.dyn_array = [1, 2, 3]
    self.h =  [123456789]
    self.foo[0] = [987, 654, 321]
    self.foo[1] = [123, 456, 789]

@external
@nonreentrant
def with_lock():
    pass
"""


def test_storage_slots(get_contract):
    c = get_contract(code)
    assert c.a() == ("ok", [4, 5, 6])
    assert [c.b(i) for i in range(2)] == [7, 8]
    assert c.c() == b"thisisthirtytwobytesokhowdoyoudo"
    assert [c.d(i) for i in range(4)] == [-1, -2, -3, -4]
    assert c.e() == "A realllllly long string but we won't use it all"
    assert c.f(0) == 33
    assert c.g(0) == (b"hello", [-66, 420], "another string")
    assert c.g(1) == (
        b"gbye",
        [1337, 888],
        "whatifthisstringtakesuptheentirelengthwouldthatbesobadidothinkso",
    )
    assert [c.foo(0, i) for i in range(3)] == [987, 654, 321]
    assert [c.foo(1, i) for i in range(3)] == [123, 456, 789]
    assert c.h(0) == 123456789


def test_reentrancy_lock(get_contract):
    c = get_contract(code)

    # if re-entrancy locks are incorrectly placed within storage, these
    # calls will either revert or correupt the data that we read later
    c.with_lock()

    assert c.a() == ("ok", [4, 5, 6])
    assert [c.b(i) for i in range(2)] == [7, 8]
    assert c.c() == b"thisisthirtytwobytesokhowdoyoudo"
    assert [c.d(i) for i in range(4)] == [-1, -2, -3, -4]
    assert c.e() == "A realllllly long string but we won't use it all"
    assert c.f(0) == 33
    assert c.g(0) == (b"hello", [-66, 420], "another string")
    assert c.g(1) == (
        b"gbye",
        [1337, 888],
        "whatifthisstringtakesuptheentirelengthwouldthatbesobadidothinkso",
    )
    assert [c.foo(0, i) for i in range(3)] == [987, 654, 321]
    assert [c.foo(1, i) for i in range(3)] == [123, 456, 789]
    assert c.h(0) == 123456789


def test_allocator_overflow(get_contract):
    code = """
# --> global nonreentrancy slot allocated here <--
y: uint256[max_value(uint256)]
    """
    with pytest.raises(
        StorageLayoutException,
        match=f"Invalid storage slot, tried to allocate slots 1 through {2**256}",
    ):
        get_contract(code)
