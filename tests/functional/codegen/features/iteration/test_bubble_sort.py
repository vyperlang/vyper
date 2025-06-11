import pytest

"""
Test vyper implementation of bubble sort. Good functional test as it
stresses the code generator and optimizer a little.
"""

def test_bubble_sort(get_contract):
    code = """
MAX_DATA_SIZE: constant(uint256) = 100

data: DynArray[uint256, MAX_DATA_SIZE]

@internal
@view
def _validate_index(idx: uint256):
    assert idx < len(self.data), "Index out of bounds"

@internal
def _swap(i: uint256, j: uint256):
    self._validate_index(i)
    self._validate_index(j)
    temp: uint256 = self.data[i]
    self.data[i] = self.data[j]
    self.data[j] = temp

@internal
def _bubble_sort():
    n: uint256 = len(self.data)
    for i: uint256 in range(n, bound=MAX_DATA_SIZE):
        for j: uint256 in range(n - i - 1, bound=MAX_DATA_SIZE):
            if self.data[j] > self.data[j + 1]:
                self._swap(j, j + 1)

@external
def add(val: uint256):
    self.data.append(val)

@external
def sort_data():
    self._bubble_sort()

@external
@view
def get(idx: uint256) -> uint256:
    self._validate_index(idx)
    return self.data[idx]
"""

    c = get_contract(code)

    # add unsorted data
    c.add(5)
    c.add(2)
    c.add(8)
    c.add(1)

    # sort
    c.sort_data()

    # check sorted
    results = [c.get(i) for i in range(4)]
    print(f"After sorting: {results}")

    assert results == [1, 2, 5, 8]
