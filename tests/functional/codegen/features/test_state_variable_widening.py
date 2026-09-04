import pytest

SHORT = [b"a", b"0123456789", b""]
NESTED = [[1, 2], [], [3]]


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
    # deprecated spelling of `self.X`, still accepted
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

@external
def via_local() -> DynArray[DynArray[uint256, 4], 3]:
    ys: DynArray[DynArray[uint256, 4], 3] = self.X
    return ys

@external
def via_return() -> DynArray[DynArray[uint256, 4], 3]:
    return self.X
    """
    c = get_contract(code, NESTED)
    assert c.via_local() == NESTED
    assert c.via_return() == NESTED


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
