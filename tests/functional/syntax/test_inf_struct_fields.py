import pytest

from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.exceptions import ImmutableViolation, StructureException, VyperException

BATCH = """
struct Batch:
    owner: address
    values: DynArray[uint256, INF]
"""


# every case here must fail in the frontend: `pytest.raises(VyperException)`
# does not catch a `CompilerPanic`, which derives from a separate base
fail_list = [
    # a member that holds INF below the top level has no pointer cell
    (
        """
struct S:
    x: (Bytes[INF], uint256)
    """,
        "Struct members cannot contain unbounded sequence types",
    ),
    (
        """
struct Batch:
    values: DynArray[uint256, INF]

struct S:
    xs: DynArray[Batch, 3]
    """,
        "Struct members cannot contain unbounded sequence types",
    ),
    # mutation of a member would also be visible through every struct copy
    (
        BATCH + """
@external
def f(b: Batch, v: DynArray[uint256, INF]):
    c: Batch = b
    c.values = v
    """,
        "Cannot modify an unbounded sequence member of a struct",
    ),
    (
        BATCH + """
@external
def f(b: Batch):
    c: Batch = b
    c.values[0] = 5
    """,
        "Cannot modify an unbounded sequence member of a struct",
    ),
    (
        BATCH + """
@external
def f(b: Batch):
    c: Batch = b
    c.values.append(1)
    """,
        "Cannot modify an unbounded sequence member of a struct",
    ),
    (
        BATCH + """
@external
def f(b: Batch) -> uint256:
    c: Batch = b
    return c.values.pop()
    """,
        "Cannot modify an unbounded sequence member of a struct",
    ),
    (
        BATCH + """
struct Outer:
    inner: Batch

@external
def f(o: Outer):
    c: Outer = o
    c.inner.values.append(1)
    """,
        "Cannot modify an unbounded sequence member of a struct",
    ),
    # state variables of every word-addressed location stay rejected
    (BATCH + "\ns: Batch\n", "Module variables cannot use unbounded sequence types"),
    (BATCH + "\ns: transient(Batch)\n", "Module variables cannot use unbounded sequence types"),
    (
        BATCH + """
s: immutable(Batch)

@deploy
def __init__(b: Batch):
    s = b
    """,
        "Module variables cannot use unbounded sequence types",
    ),
    (
        BATCH + """
C: constant(Batch) = Batch(owner=empty(address), values=[1, 2])
    """,
        "Constants cannot contain unbounded sequence types",
    ),
    (BATCH + "\nm: HashMap[uint256, Batch]\n", "Module variables cannot use unbounded sequence"),
    (
        BATCH + """
@external
def f(bs: Batch[2]) -> uint256:
    return 1
    """,
        "Static arrays of unbounded sequence types are not supported",
    ),
    # decoding would have to rebuild the pointer cells
    (
        BATCH + """
@external
def f(d: Bytes[1024]) -> uint256:
    b: Batch = abi_decode(d, Batch)
    return len(b.values)
    """,
        "abi_decode output type cannot contain unbounded sequence types",
    ),
    # the encoded size has no static bound, so these buffers cannot be sized
    (
        BATCH + """
@external
def f(b: Batch) -> Bytes[INF]:
    return abi_encode(b)
    """,
        "abi_encode arguments cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
@external
def f(bs: DynArray[Batch, INF]) -> DynArray[Batch, INF]:
    return bs
    """,
        "Function returns cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
@external
def f(b: Batch) -> (uint256, Batch):
    return 1, b
    """,
        "Function returns cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
interface I:
    def take(b: Batch): nonpayable

@external
def f(a: address, b: Batch):
    extcall I(a).take(b)
    """,
        "Function arguments cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
interface I:
    def make() -> Batch: view

@external
def f(a: address) -> uint256:
    b: Batch = staticcall I(a).make()
    return len(b.values)
    """,
        "External call returns cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
@external
def f(t: address, b: Batch) -> address:
    return create_from_blueprint(t, b, code_offset=3)
    """,
        "constructor arguments cannot contain nested unbounded sequence types",
    ),
    (
        BATCH + """
event E:
    b: Batch
    """,
        "Event members cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
error E:
    b: Batch
    """,
        "Custom error members cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
@external
def f(b: Batch):
    print(b)
    """,
        "print arguments cannot contain unbounded sequence types",
    ),
    (
        BATCH + """
@external
def f() -> uint256:
    b: Batch = empty(Batch)
    return len(b.values)
    """,
        "empty() does not support unbounded sequence types",
    ),
]


@pytest.mark.parametrize("bad_code,message", fail_list)
def test_inf_struct_field_fail(bad_code, message):
    with pytest.raises(VyperException) as e:
        compile_code(bad_code, settings=Settings(experimental_codegen=True))

    assert isinstance(e.value, StructureException)
    assert message in str(e.value)


def test_module_constant_assignment_keeps_its_own_error(make_input_bundle):
    # a module constant is the other lvalue whose attribute has an unbounded
    # type, and it must not be reported as a struct member
    lib = """
X: public(constant(Bytes[INF])) = b"hello"
    """
    code = """
import lib

@external
def f():
    lib.X = b"bye"
    """

    input_bundle = make_input_bundle({"lib.vy": lib})
    with pytest.raises(ImmutableViolation) as e:
        compile_code(code, settings=Settings(experimental_codegen=True), input_bundle=input_bundle)

    assert "Constant value cannot be written to" in str(e.value)


def test_inf_struct_field_rejected_without_venom():
    code = BATCH + """
@external
def f(b: Batch) -> uint256:
    return len(b.values)
    """

    with pytest.raises(StructureException) as e:
        compile_code(code, settings=Settings(experimental_codegen=False))

    assert "unbounded sequence types require --experimental-codegen" in str(e.value)
