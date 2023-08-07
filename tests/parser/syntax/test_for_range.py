import pytest

from vyper import compiler
from vyper.exceptions import StructureException

fail_list = [
    (
        """
@external
def foo():
    for a[1] in range(10):
        pass
    """,
        StructureException,
    )
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_range_fail(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
@external
def foo():
    for i in range(10):
        pass
    """,
    """
@external
def foo():
    for i in range(10, 20):
        pass
    """,
    """
@external
def foo():
    x: int128 = 5
    for i in range(x, x + 10):
        pass
    """,
    """
interface Foo:
    def kick(): nonpayable
foos: Foo[3]
@external
def kick_foos():
    for foo in self.foos:
        foo.kick()
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_range_success(good_code):
    assert compiler.compile_code(good_code) is not None


fail_list = [
    # Cannot call `pop()` in for range because it modifies state
    (
        """
arr: DynArray[uint256, 10]

@external
def test()-> (DynArray[uint256, 6], DynArray[uint256, 10]):
    b: DynArray[uint256, 6] = []

    self.arr = [1,0]

    for i in range(self.arr.pop(), self.arr.pop() + 2):
        b.append(i)

    return b, self.arr
    """,
        ImmutableViolation,
    )
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_range_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
