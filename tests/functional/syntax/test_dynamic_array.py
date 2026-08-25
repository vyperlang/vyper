import pytest

from vyper import compile_code
from vyper.exceptions import (
    ArrayIndexException,
    CompilerPanic,
    ImmutableViolation,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
)

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
def foo():
    [].append(1)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    x: uint256 = [].pop()
    """,
        # this branch rejects mutating a temporary instead of panicking
        ImmutableViolation,
    ),
    (
        """
@external
def foo() -> uint256:
    return [][0]
    """,
        ArrayIndexException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


def test_membership_in_empty_list():
    code = """
@external
def foo():
    x: bool = 1 in []
    """
    with pytest.raises(TypeMismatch) as excinfo:
        compile_code(code)
    assert excinfo.value.message == "Cannot perform membership comparison between dislike types"


def test_dynarray_negative_length():
    code = """
@external
def foo():
    x: DynArray[uint256, -1] = []
    """
    with pytest.raises(ArrayIndexException) as excinfo:
        compile_code(code)
    assert excinfo.value.message == "Subscript must be at least 0"


valid_list = [
    """
flag Foo:
    FE
    FI

bar: DynArray[Foo, 10]
    """,  # dynamic arrays of flags are allowed, but not static arrays
    """
flag Foo:
    FE
    FI

@external
def bar():
    d: DynArray[Foo, 10] = []
    """,  # empty arrays can be assigned to dynamic arrays of flags
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
    """
@external
def foo():
    tmp: DynArray[Bytes[3], 1] = [[b"abc"], []][0]
    """,
    """
@external
def foo():
    tmp: DynArray[Bytes[3], 1] = [[], [b"abc"]][1]
    """,
    """
@external
def foo():
    x: uint256 = len([])
    """,
    """
@external
def foo():
    x: DynArray[uint256, 0] = []
    """,
    """
@external
def foo():
    x: DynArray[uint256, 4] = []
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_dynarray_pass(good_code):
    assert compile_code(good_code) is not None


def test_len_of_singleton_list_literal(request, experimental_codegen):
    if not experimental_codegen:
        request.node.add_marker(pytest.mark.xfail(raises=CompilerPanic))
    code = """
@external
def foo():
    x: uint256 = len([1])
    """
    compile_code(code)


def test_dynarray_inf_param(compile_inf_code):
    code = """
@external
def foo(x: DynArray[uint256, INF]):
    pass
    """
    compile_inf_code(code)


def test_dynarray_inf_local_var(compile_inf_code):
    code = """
@external
def foo():
    a: DynArray[uint256, INF] = []
    b: DynArray[uint256, INF] = [1, 2, 3, 4, 5, max_value(uint256)]
    """
    compile_inf_code(code)


@pytest.mark.parametrize(
    "code,msg",
    [
        (
            "a: DynArray[DynArray[uint256, INF], 5]",
            "DynArray element types cannot contain unbounded sequence types",
        ),
        (
            "a: DynArray[Bytes[INF], 5]",
            "DynArray element types cannot contain unbounded sequence types",
        ),
        (
            "a: DynArray[DynArray[uint256, 5], INF]",
            "DynArray[..., INF] is only supported with ABI-static element types",
        ),
        (
            "a: DynArray[Bytes[5], INF]",
            "DynArray[..., INF] is only supported with ABI-static element types",
        ),
    ],
)
def test_dynarray_inf_nested(code, msg):
    with pytest.raises(StructureException) as e:
        compile_code(code)
    assert e.value.message == msg


def test_dynarray_inf_append(compile_inf_code):
    code = """
@external
def foo():
    a: DynArray[uint256, INF] = []
    a.append(1)
    """
    compile_inf_code(code)


def test_dynarray_mutating_temporary_rejected():
    for code in (
        """
@external
def foo():
    empty(DynArray[uint256, 5]).append(1)
        """,
        """
@internal
def _xs() -> DynArray[uint256, INF]:
    return [1, 2]

@external
def foo():
    self._xs().append(3)
        """,
        """
@external
def foo() -> uint256:
    return empty(DynArray[uint256, INF]).pop()
        """,
    ):
        with pytest.raises(ImmutableViolation) as e:
            compile_code(code)
        assert e.value.message == "Cannot modify temporary value"


def test_dynarray_inf_assign_bounded_to_unbounded(compile_inf_code):
    code = """
@external
def foo():
    a: DynArray[uint256, 5] = [1, 2, 3]
    b: DynArray[uint256, INF] = a
    """
    compile_inf_code(code)
