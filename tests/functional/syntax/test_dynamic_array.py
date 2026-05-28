import pytest

from vyper import compile_code
from vyper.exceptions import CodegenPanic, StructureException, TypeMismatch, UndeclaredDefinition

fail_list = [
    (
        """
foo: DynArray[HashMap[uint8, uint8], 2]
    """,
        StructureException,
    ),
    (
        """
foo: public(DynArray[HashMap[uint8, uint8], 2])
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    a: DynArray = [1, 2, 3]
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    a: DynArray[uint256, FOO] = [1, 2, 3]
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def foo(x: DynArray[uint256, INF + 1]):
    pass
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(x: DynArray[uint256, INF - 1]):
    pass
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(x: DynArray[uint256, inf]):
    pass
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def foo(x: DynArray[uint256, INF]) -> DynArray[uint256, 5]:
    return x
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
flag Foo:
    FE
    FI

bar: DynArray[Foo, 10]
    """,  # dynamic arrays of flags are allowed, but not static arrays
    """
bar: DynArray[Bytes[30], 10]
    """,  # dynamic arrays of bytestrings are allowed, but not static arrays
    """
@external
def bar():
    d: DynArray[uint256, 10] = []
    i: DynArray[uint256, 30] = d
    """,  # dynamic arrays can be assigned to others of larger size
    """
@external
def bar():
    d: DynArray[DynArray[uint256, 10], 10] = [[]]
    for i: DynArray[uint256, 30] in d:
        pass
    """,  # dynamic arrays can be assigned to others of larger size
    """
FOO: constant(uint256) = 4

@external
def foo():
    a: DynArray[uint256, FOO] = [1, 2, 3]
    """,  # dynamic arrays can take constants as length
    """
interface IFoo:
    def bar() -> DynArray[uint256, INF]: nonpayable
    """,  # DynArray with INF in interface return type
    """
interface IFoo:
    def bar() -> DynArray[uint256, ...]: nonpayable
    """,  # DynArray with wildcard in interface return type
]


@pytest.mark.parametrize("good_code", valid_list)
def test_dynarray_pass(good_code):
    assert compile_code(good_code) is not None


@pytest.mark.xfail(raises=CodegenPanic, reason="unbounded sequence types not yet fully supported")
def test_dynarray_inf_param():
    code = """
@external
def foo(x: DynArray[uint256, INF]):
    pass
    """
    compile_code(code)


@pytest.mark.xfail(raises=CodegenPanic, reason="unbounded sequence types not yet fully supported")
def test_dynarray_inf_state_var():
    code = """
a: DynArray[uint256, INF]

@external
def foo() -> DynArray[uint256, INF]:
    return self.a
    """
    compile_code(code)


@pytest.mark.xfail(raises=CodegenPanic, reason="unbounded sequence types not yet fully supported")
def test_dynarray_inf_local_var():
    code = """
@external
def foo():
    a: DynArray[uint256, INF] = []
    b: DynArray[uint256, INF] = [1, 2, 3, 4, 5, max_value(uint256)]
    """
    compile_code(code)


@pytest.mark.xfail(raises=CodegenPanic, reason="unbounded sequence types not yet fully supported")
def test_dynarray_inf_nested():
    code = """
a: DynArray[DynArray[uint256, 5], INF]
b: DynArray[DynArray[uint256, INF], 5]

@external
def foo(other_a: DynArray[DynArray[uint256, 5], INF]) -> DynArray[DynArray[uint256, 5], INF]:
    return self.a

@external
def bar(other_b: DynArray[DynArray[uint256, INF], 5]) -> DynArray[DynArray[uint256, INF], 5]:
    return self.b
    """
    compile_code(code)


@pytest.mark.xfail(raises=CodegenPanic, reason="unbounded sequence types not yet fully supported")
def test_dynarray_inf_append():
    code = """
@external
def foo():
    a: DynArray[uint256, INF] = []
    a.append(1)
    """
    compile_code(code)


@pytest.mark.xfail(raises=CodegenPanic, reason="unbounded sequence types not yet fully supported")
def test_dynarray_inf_assign_bounded_to_unbounded():
    code = """
@external
def foo():
    a: DynArray[uint256, 5] = [1, 2, 3]
    b: DynArray[uint256, INF] = a
    """
    compile_code(code)
