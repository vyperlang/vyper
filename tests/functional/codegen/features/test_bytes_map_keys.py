import pytest

from vyper.exceptions import TypeMismatch


def test_basic_bytes_keys(env, get_contract):
    code = """
mapped_bytes: HashMap[Bytes[5], int128]

@external
def set(k: Bytes[5], v: int128):
    self.mapped_bytes[k] = v

@external
def get(k: Bytes[5]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(b"test", 54321)

    assert c.get(b"test") == 54321


def test_basic_bytes_literal_key(get_contract):
    code = """
mapped_bytes: HashMap[Bytes[5], int128]

@external
def set(v: int128):
    self.mapped_bytes[b"test"] = v

@external
def get(k: Bytes[5]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(54321)

    assert c.get(b"test") == 54321


def test_basic_long_bytes_as_keys(get_contract):
    code = """
mapped_bytes: HashMap[Bytes[34], int128]

@external
def set(k: Bytes[34], v: int128):
    self.mapped_bytes[k] = v

@external
def get(k: Bytes[34]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(b"a" * 34, 6789, gas=10**6)

    assert c.get(b"a" * 34) == 6789


def test_mismatched_byte_length(get_contract):
    code = """
mapped_bytes: HashMap[Bytes[34], int128]

@external
def set(k: Bytes[35], v: int128):
    self.mapped_bytes[k] = v
    """

    with pytest.raises(TypeMismatch):
        get_contract(code)


def test_extended_bytes_key_from_storage(get_contract):
    code = """
a: HashMap[Bytes[100000], int128]

@deploy
def __init__():
    self.a[b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] = 1069

@external
def get_it1() -> int128:
    key: Bytes[100000] = b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    return self.a[key]

@external
def get_it2() -> int128:
    return self.a[b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]

@external
def get_it3(key: Bytes[100000]) -> int128:
    return self.a[key]
    """

    c = get_contract(code)

    assert c.get_it2() == 1069
    assert c.get_it2() == 1069
    assert c.get_it3(b"a" * 33) == 1069
    assert c.get_it3(b"test") == 0


def test_struct_bytes_key_memory(get_contract):
    code = """
struct Foo:
    one: Bytes[5]
    two: Bytes[100]

a: HashMap[Bytes[100000], int128]

@deploy
def __init__():
    self.a[b"hello"] = 1069
    self.a[b"potato"] = 31337

@external
def get_one() -> int128:
    b: Foo = Foo(one=b"hello", two=b"potato")
    return self.a[b.one]

@external
def get_two() -> int128:
    b: Foo = Foo(one=b"hello", two=b"potato")
    return self.a[b.two]
"""

    c = get_contract(code)

    assert c.get_one() == 1069
    assert c.get_two() == 31337


def test_struct_bytes_key_storage(get_contract):
    code = """
struct Foo:
    one: Bytes[5]
    two: Bytes[100]

a: HashMap[Bytes[100000], int128]
b: Foo

@deploy
def __init__():
    self.a[b"hello"] = 1069
    self.a[b"potato"] = 31337
    self.b = Foo(one=b"hello", two=b"potato")

@external
def get_one() -> int128:
    return self.a[self.b.one]

@external
def get_two() -> int128:
    return self.a[self.b.two]
"""

    c = get_contract(code)

    assert c.get_one() == 1069
    assert c.get_two() == 31337


def test_bytes_key_storage(get_contract):
    code = """

a: HashMap[Bytes[100000], int128]
b: Bytes[5]

@deploy
def __init__():
    self.a[b"hello"] = 1069
    self.b = b"hello"

@external
def get_storage() -> int128:
    return self.a[self.b]
"""

    c = get_contract(code)

    assert c.get_storage() == 1069


def test_bytes_key_calldata(get_contract):
    code = """

a: HashMap[Bytes[100000], int128]


@deploy
def __init__():
    self.a[b"hello"] = 1069

@external
def get_calldata(b: Bytes[5]) -> int128:
    return self.a[b]
"""

    c = get_contract(code)

    assert c.get_calldata(b"hello") == 1069


def test_struct_bytes_hashmap_as_key_in_other_hashmap(get_contract):
    code = """
struct Thing:
    name: Bytes[64]

bar: public(HashMap[uint256, Thing])
foo: public(HashMap[Bytes[64], uint256])

@deploy
def __init__():
    self.foo[b"hello"] = 31337
    self.bar[12] = Thing(name=b"hello")

@external
def do_the_thing(_index: uint256) -> uint256:
    return self.foo[self.bar[_index].name]
    """

    c = get_contract(code)

    assert c.do_the_thing(12) == 31337


# copying a narrow key out of storage, transient storage or immutables
# must be sized by the key's own type, not by the map's key type:
# the cost must not scale with the map's declared key size.
NARROW_KEY_GAS_BOUND = 100_000


@pytest.mark.parametrize("typ,key", [("Bytes", b"hello"), ("String", "hello")])
@pytest.mark.parametrize("location", ["storage", "immutable"])
def test_narrow_key_into_wide_map(env, get_contract, typ, key, location):
    if location == "storage":
        decl, init, k = f"b: {typ}[5]", "self.b = k", "self.b"
    else:
        decl, init, k = f"B: immutable({typ}[5])", "B = k", "self.B"

    code = f"""
a: HashMap[{typ}[100000], int128]
{decl}

@deploy
def __init__(k: {typ}[5]):
    {init}

@external
def set_narrow(v: int128):
    self.a[{k}] = v

@external
def get_narrow() -> int128:
    return self.a[{k}]

@external
def get_wide(k: {typ}[100000]) -> int128:
    return self.a[k]
    """

    c = get_contract(code, key)

    c.set_narrow(1069)
    assert env.last_result.gas_used < NARROW_KEY_GAS_BOUND
    assert c.get_wide(key) == 1069

    assert c.get_narrow() == 1069
    assert env.last_result.gas_used < NARROW_KEY_GAS_BOUND


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("typ,key", [("Bytes", b"hello"), ("String", "hello")])
def test_narrow_transient_key_into_wide_map(env, get_contract, typ, key):
    code = f"""
a: HashMap[{typ}[100000], int128]
b: transient({typ}[5])

@external
def set_narrow(k: {typ}[5], v: int128):
    self.b = k
    self.a[self.b] = v

@external
def get_narrow(k: {typ}[5]) -> int128:
    self.b = k
    return self.a[self.b]

@external
def get_wide(k: {typ}[100000]) -> int128:
    return self.a[k]
    """

    c = get_contract(code)

    c.set_narrow(key, 1069)
    assert env.last_result.gas_used < NARROW_KEY_GAS_BOUND
    assert c.get_wide(key) == 1069

    assert c.get_narrow(key) == 1069
    assert env.last_result.gas_used < NARROW_KEY_GAS_BOUND
