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
    (
        """
@external
def foo(x: DynArray[Bytes[5], INF]):
    pass
    """,
        StructureException,
    ),
    (
        """
@external
def foo(x: DynArray[Bytes[INF], 5]):
    pass
    """,
        StructureException,
    ),
    (
        """
@external
def foo(x: DynArray[DynArray[uint256, 5], INF]):
    pass
    """,
        StructureException,
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
    """
interface IFoo:
    def bar() -> DynArray[Bytes[10], ...]: nonpayable
    """,  # DynArray with wildcard in interface return type can have dynamic elements
]


@pytest.mark.parametrize("good_code", valid_list)
def test_dynarray_pass(good_code):
    assert compile_code(good_code) is not None


def _compile_inf_dynarray_code(code, experimental_codegen):
    if experimental_codegen:
        compile_code(code)
    else:
        with pytest.raises(CodegenPanic):
            compile_code(code)


def test_dynarray_inf_param(experimental_codegen):
    code = """
@external
def foo(x: DynArray[uint256, INF]):
    pass
    """
    _compile_inf_dynarray_code(code, experimental_codegen)


def test_dynarray_inf_state_var():
    code = """
a: DynArray[uint256, INF]

@external
def foo() -> DynArray[uint256, INF]:
    return self.a
    """
    with pytest.raises(StructureException):
        compile_code(code)


def test_dynarray_inf_local_var(experimental_codegen):
    code = """
@external
def foo():
    a: DynArray[uint256, INF] = []
    b: DynArray[uint256, INF] = [1, 2, 3, 4, 5, max_value(uint256)]
    """
    _compile_inf_dynarray_code(code, experimental_codegen)


def test_dynarray_inf_nested():
    for code in (
        """
a: DynArray[DynArray[uint256, 5], INF]
        """,
        """
b: DynArray[DynArray[uint256, INF], 5]
        """,
    ):
        with pytest.raises(StructureException):
            compile_code(code)


def test_dynarray_inf_append(experimental_codegen):
    code = """
@external
def foo():
    a: DynArray[uint256, INF] = []
    a.append(1)
    """
    _compile_inf_dynarray_code(code, experimental_codegen)


def test_dynarray_inf_assign_bounded_to_unbounded(experimental_codegen):
    code = """
@external
def foo():
    a: DynArray[uint256, 5] = [1, 2, 3]
    b: DynArray[uint256, INF] = a
    """
    _compile_inf_dynarray_code(code, experimental_codegen)
