# TODO: rewrite the tests in type-centric way, parametrize array and indices types

import pytest

from vyper.exceptions import CompilerPanic


def test_negative_ix_access(get_contract, tx_failed):
    # Arrays can't be accessed with negative indices
    code = """
arr: uint256[3]

@external
def foo(i: int128):
    self.arr[i] = 1
    """

    c = get_contract(code)

    with tx_failed():
        c.foo(-1)
    with tx_failed():
        c.foo(-3)
    with tx_failed():
        c.foo(-(2**127) + 1)


def test_negative_ix_access_to_large_arr(get_contract, tx_failed):
    # Arrays can't be accessed with negative indices
    code = """
arr: public(uint256[max_value(uint256)-1])

@external
def set(idx: int256):
    self.arr[idx] = 1
    """

    c = get_contract(code)
    with tx_failed():
        c.set(-(2**255))
    with tx_failed():
        c.set(-(2**255) + 5)
    with tx_failed():
        c.set(-(2**128))
    with tx_failed():
        c.set(-1)


def test_oob_access_to_large_arr(get_contract, tx_failed):
    # Test OOB access to large array
    code = """
arr: public(uint256[max_value(uint256)-1])

@external
def set(idx: int256):
    self.arr[idx] = 3

@external
def set2(idx: uint256):
    self.arr[idx] = 3
    """
    c = get_contract(code)

    with tx_failed():
        c.set2(2**256 - 1)
    with tx_failed():
        c.set2(2**256 - 2)


def test_boundary_access_to_arr(get_contract):
    # Test access to the boundary of the array
    code = """
arr1: public(int256[max_value(int256)])

@external
def set1(idx: int256):
    self.arr1[idx] = 3

    """
    code2 = """
arr2: public(uint256[max_value(uint256)-1])

@external
def set2(idx: uint256):
    self.arr2[idx] = 3
    """
    c1 = get_contract(code)

    c1.set1(2**255 - 2)
    assert c1.arr1(2**255 - 2) == 3
    c1.set1(0)
    assert c1.arr1(0) == 3

    c2 = get_contract(code2)

    c2.set2(2**256 - 3)
    assert c2.arr2(2**256 - 3) == 3


def test_valid_ix_access(get_contract):
    code = """
arr: public(uint256[3])
arr2: public(int256[3])

@external
def foo(i: int128):
    self.arr[i] = 1

@external
def bar(i: uint256):
    self.arr[i] = 2
    """

    c = get_contract(code)
    for i in range(3):
        c.foo(i)
        assert c.arr(i) == 1
        c.bar(i)
        assert c.arr(i) == 2


def test_for_loop_ix_access(get_contract):
    # Arrays can be accessed with for loop iterators of type int
    code = """
arr: public(int256[10])

@external
def foo():
    for i: int256 in range(10):
        self.arr[i] = i
    """

    c = get_contract(code)
    c.foo()
    for i in range(10):
        assert c.arr(i) == i


# to fix in future release
@pytest.mark.xfail(raises=CompilerPanic, reason="risky overlap")
def test_array_index_overlap(get_contract):
    code = """
a: public(DynArray[DynArray[Bytes[96], 5], 5])

@external
def foo() -> Bytes[96]:
    self.a.append([b'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'])
    return self.a[0][self.bar()]


@internal
def bar() -> uint256:
    self.a[0] = [b'yyy']
    self.a.pop()
    return 0
    """
    c = get_contract(code)
    # tricky to get this right, for now we just panic instead of generating code
    assert c.foo() == b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


# to fix in future release
@pytest.mark.xfail(raises=CompilerPanic, reason="risky overlap")
def test_array_index_overlap_extcall(get_contract):
    code = """

interface Bar:
    def bar() -> uint256: payable

a: public(DynArray[DynArray[Bytes[96], 5], 5])

@external
def foo() -> Bytes[96]:
    self.a.append([b'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'])
    return self.a[0][extcall Bar(self).bar()]


@external
def bar() -> uint256:
    self.a[0] = [b'yyy']
    self.a.pop()
    return 0
    """
    c = get_contract(code)
    assert c.foo() == b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


# to fix in future release
@pytest.mark.xfail(raises=CompilerPanic, reason="risky overlap")
def test_array_index_overlap_extcall2(get_contract):
    code = """
interface B:
    def calculate_index() -> uint256: nonpayable

a: HashMap[uint256, DynArray[uint256, 5]]

@external
def bar() -> uint256:
    self.a[0] = [2]
    return self.a[0][extcall B(self).calculate_index()]

@external
def calculate_index() -> uint256:
    self.a[0] = [1]
    return 0
    """
    c = get_contract(code)

    assert c.bar() == 1
