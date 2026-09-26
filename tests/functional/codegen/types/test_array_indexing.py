# TODO: rewrite the tests in type-centric way, parametrize array and indices types

import pytest

from vyper import compile_code
from vyper.exceptions import CompilerPanic, InvalidOperation, TypeCheckFailure


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


def test_array_index_overlap(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.xfail("legacy codegen still rejects risky subscript overlap")

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
    assert c.foo() == b"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def test_array_index_overlap_extcall(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.xfail("legacy codegen still rejects risky subscript overlap")

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


def test_array_index_overlap_extcall2(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.xfail("legacy codegen still rejects risky subscript overlap")

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


def test_array_index_overlap_attribute(get_contract, experimental_codegen):
    if not experimental_codegen:
        pytest.xfail("legacy codegen still rejects risky subscript overlap")

    code = """
struct Foo:
    b: DynArray[uint256, 4]

a: DynArray[Foo, 5]

@external
def foo() -> uint256:
    self.a.append(Foo(b=[1, 1, 1, 1]))
    return self.a[0].b[self.bar()]

@internal
def bar() -> uint256:
    self.a[0] = Foo(b=[100, 100, 100, 100])
    self.a.pop()
    return 0
    """
    c = get_contract(code)
    assert c.foo() == 1


# to fix in future release
@pytest.mark.xfail(raises=CompilerPanic, reason="risky overlap")
def test_array_index_overlap_store(get_contract):
    code = """
a: DynArray[DynArray[uint256, 5], 5]

@external
def foo() -> uint256:
    self.a.append([1])
    self.a[0][self.bar()] = 7
    return self.a[0][0]

@internal
def bar() -> uint256:
    self.a.pop()
    self.a.append([2])
    return 0
    """
    c = get_contract(code)
    assert c.foo() == 7


# to fix in future release
@pytest.mark.xfail(raises=CompilerPanic, reason="risky overlap")
def test_array_index_overlap_store_attribute(get_contract):
    code = """
struct Foo:
    b: DynArray[uint256, 4]

a: DynArray[Foo, 5]

@external
def foo() -> uint256:
    self.a.append(Foo(b=[1, 1, 1, 1]))
    self.a[0].b[self.bar()] = 7
    return self.a[0].b[0]

@internal
def bar() -> uint256:
    self.a.pop()
    self.a.append(Foo(b=[2, 2, 2, 2]))
    return 0
    """
    c = get_contract(code)
    assert c.foo() == 7


# to fix in future release
@pytest.mark.xfail(raises=CompilerPanic, reason="risky overlap")
def test_array_index_overlap_store_attribute_target(get_contract):
    code = """
struct Foo:
    b: uint256

a: DynArray[DynArray[Foo, 4], 5]

@external
def foo() -> uint256:
    self.a.append([Foo(b=1)])
    self.a[0][self.bar()].b = 7
    return self.a[0][0].b

@internal
def bar() -> uint256:
    self.a.pop()
    self.a.append([Foo(b=2)])
    return 0
    """
    c = get_contract(code)
    assert c.foo() == 7


def test_append_to_row_popped_by_argument(get_contract, tx_failed):
    code = """
@external
def foo() -> DynArray[DynArray[uint256, 3], 3]:
    rows: DynArray[DynArray[uint256, 3], 3] = [[1], [2]]
    rows[1].append(rows.pop()[0])
    return rows
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()


def test_append_to_row_popped_by_argument_storage(get_contract, tx_failed):
    code = """
rows: DynArray[DynArray[uint256, 3], 3]

@external
def seed():
    self.rows = [[1], [2]]

@external
def foo() -> DynArray[DynArray[uint256, 3], 3]:
    self.rows[1].append(self.bar())
    return self.rows

@internal
def bar() -> uint256:
    self.rows.pop()
    return 5
    """
    c = get_contract(code)
    c.seed()
    with tx_failed():
        c.foo()


@pytest.mark.parametrize("index", [0, 1])
def test_append_to_row_in_popped_outer_array(get_contract, tx_failed, index):
    code = """
@external
def foo(index: uint256) -> DynArray[DynArray[DynArray[uint256, 3], 3], 3]:
    rows: DynArray[DynArray[DynArray[uint256, 3], 3], 3] = [[[1]], [[2]]]
    rows[index][0].append(rows.pop()[0][0])
    return rows
    """
    c = get_contract(code)
    if index == 1:
        with tx_failed():
            c.foo(index)
    else:
        assert c.foo(index) == [[[1, 2]]]


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("index", [0, 1])
def test_append_to_row_popped_by_argument_transient(get_contract, tx_failed, index):
    code = """
rows: transient(DynArray[DynArray[uint256, 3], 3])

@external
def foo(xs: DynArray[DynArray[uint256, 3], 3], index: uint256) -> DynArray[DynArray[uint256, 3], 3]:
    self.rows = xs
    self.rows[index].append(self.bar())
    return self.rows

@internal
def bar() -> uint256:
    self.rows.pop()
    return 5
    """
    c = get_contract(code)
    if index == 1:
        with tx_failed():
            c.foo([[1], [2]], index)
    else:
        assert c.foo([[1], [2]], index) == [[1, 5]]


# TODO: When it also raises with venom, move this back to analysis
def test_index_empty_list_variable_index(request, env, tx_failed, experimental_codegen):
    code = """
@external
def foo(i: uint256) -> uint256:
    return [][i]
    """
    if not experimental_codegen:
        # Legacy IR rejects `[][i]` at compile time.
        with pytest.raises(TypeCheckFailure):
            compile_code(code)
        pytest.xfail("should fail with a user-facing error, not a VyperInternalException")

    # Venom does not have the sanity check, so it compiles (it shouldn't hence xfail)
    # Make sure at least the bytecode is correct (always reverts)

    # bytecode-only: requesting `abi` forces legacy IR, which independently raises TypeCheckFailure.
    out = compile_code(code, output_formats=["bytecode"])
    bytecode = bytes.fromhex(out["bytecode"].removeprefix("0x"))
    abi = [
        {
            "type": "function",
            "name": "foo",
            "stateMutability": "pure",
            "inputs": [{"name": "i", "type": "uint256"}],
            "outputs": [{"type": "uint256"}],
        }
    ]
    c = env.deploy(abi, bytecode)
    with tx_failed():
        c.foo(0)
    pytest.xfail("compilation succeeded with correct bytecode, but should have rejected `[][i]`")


@pytest.mark.xfail(raises=InvalidOperation)
def test_index_all_empty_lists_variable_index(get_contract, tx_failed):
    code = """
@external
def foo(i: uint256) -> DynArray[uint256, 5]:
    return [[], []][i]
    """

    c = get_contract(code)

    assert c.foo(0) == []
    assert c.foo(1) == []
    with tx_failed():
        c.foo(2)
