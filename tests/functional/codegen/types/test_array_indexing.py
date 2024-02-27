import pytest
from eth_tester.exceptions import TransactionFailed

# TODO: rewrite the tests in type-centric way, parametrize array and indices types


def test_negative_ix_access(get_contract):
    # Arrays can't be accessed with negative indices
    code = """
arr: uint256[3]

@external
def foo(i: int128):
    self.arr[i] = 1
    """

    c = get_contract(code)

    with pytest.raises(TransactionFailed):
        c.foo(-1)
        c.foo(-3)
        c.foo(-(2**127) + 1)


def test_negative_ix_access_to_large_arr(get_contract):
    # Arrays can't be accessed with negative indices
    code = """
arr: public(uint256[max_value(uint256)-1])

@external
def set(idx: int256):
    self.arr[idx] = 1
    """

    c = get_contract(code)
    with pytest.raises(TransactionFailed):
        c.set(-(2**255))
        c.set(-(2**255) + 5)
        c.set(-(2**128))
        c.set(-1)


def test_oob_access_to_large_arr(get_contract):
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

    with pytest.raises(TransactionFailed):
        c.set2(2**256 - 1, transact={})
        c.set2(2**256 - 2, transact={})


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

    c1.set1(2**255 - 2, transact={})
    assert c1.arr1(2**255 - 2) == 3
    c1.set1(0, transact={})
    assert c1.arr1(0) == 3

    c2 = get_contract(code2)

    c2.set2(2**256 - 3, transact={})
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
        c.foo(i, transact={})
        assert c.arr(i) == 1
        c.bar(i, transact={})
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
    c.foo(transact={})
    for i in range(10):
        assert c.arr(i) == i
