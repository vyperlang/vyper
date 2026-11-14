"""
The size expression in a type annotation (`T[n]`, `Bytes[n]`, `String[n]`,
`DynArray[T, n]`) is type-checked like the value of an integer constant.
"""

import pytest

from vyper import compile_code
from vyper.exceptions import OverflowException, TypeMismatch

fail_list = [
    # an intermediate value overflows, though the folded size is 3
    (
        """
x: uint256[((1 << 256) >> 255) + 1]
    """,
        OverflowException,
    ),
    # max_value(uint8) is a uint8, so the sum overflows uint8
    (
        """
x: uint256[max_value(uint8) + 1]
    """,
        TypeMismatch,
    ),
    (
        """
x: uint256[N + 1]
N: constant(uint8) = 255
    """,
        TypeMismatch,
    ),
    # mixed integer types
    (
        """
x: uint256[K * M]
K: constant(uint8) = 2
M: constant(uint256) = 4
    """,
        TypeMismatch,
    ),
    # sizes naming constants declared after them
    (
        """
struct S:
    a: uint256[N + 1]
N: constant(uint8) = 255
    """,
        TypeMismatch,
    ),
    (
        """
event E:
    a: Bytes[K * M]
K: constant(uint8) = 2
M: constant(uint256) = 4
    """,
        TypeMismatch,
    ),
    (
        """
interface I:
    def f(a: DynArray[uint256, N + 1]): nonpayable
N: constant(uint8) = 255
    """,
        TypeMismatch,
    ),
    (
        """
@external
def f(a: String[N + 1]):
    pass
N: constant(uint8) = 255
    """,
        TypeMismatch,
    ),
    (
        """
x: HashMap[uint256, uint256[N + 1]]
N: constant(uint8) = 255
    """,
        TypeMismatch,
    ),
    # function bodies and type arguments of builtins
    (
        """
@external
def f():
    x: Bytes[max_value(uint8) + 1] = b""
    """,
        TypeMismatch,
    ),
    (
        """
@external
def f() -> uint256:
    return len(empty(DynArray[uint256, max_value(uint8) + 1]))
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_annotation_size_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


def test_annotation_size_later_constants():
    # sizes may name constants declared later in the module
    code = """
struct S:
    a: uint256[N + 1]
event E:
    a: Bytes[N + 2]
interface I:
    def g(x: DynArray[uint256, N + 3]) -> String[N + 4]: view
h: HashMap[uint256, uint256[N + 5]]
s: S

@external
def f(a: uint256[M]) -> uint256[M + 1]:
    x: uint256[M + 1] = empty(uint256[M + 1])
    return x

@external
def g(b: Bytes[200]) -> Bytes[N]:
    t: (uint256, Bytes[N]) = abi_decode(b, (uint256, Bytes[N]))
    return method_id("g()", output_type=Bytes[N])

M: constant(uint8) = N + 6
N: constant(uint8) = 4
    """
    abi = compile_code(code, output_formats=["abi"])["abi"]
    f = next(item for item in abi if item.get("name") == "f")
    assert f["inputs"][0]["type"] == "uint256[10]"
    assert f["outputs"][0]["type"] == "uint256[11]"


def test_annotation_size_decimal_subexpr():
    code = """
x: public(uint256[floor(2.5) + 1])
    """
    compile_code(code)


def test_annotation_size_imported_constant(make_input_bundle):
    lib = """
N: constant(uint8) = 3

struct T:
    a: uint256[N + 1]
    """
    code = """
import lib

x: lib.T
y: public(uint256[lib.N + 1])
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    compile_code(code, input_bundle=input_bundle)


def test_annotation_size_imported_module_fail(make_input_bundle):
    lib = """
struct T:
    a: uint256[N + 1]

N: constant(uint8) = 255
    """
    code = """
import lib

x: lib.T
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    with pytest.raises(TypeMismatch):
        compile_code(code, input_bundle=input_bundle)


def test_annotation_size_interface_file(make_input_bundle):
    ifoo = """
K: constant(uint8) = 2

@external
def foo(a: uint256[K + 1]) -> Bytes[K * 2]:
    ...
    """
    code = """
import ifoo

@external
def bar(f: ifoo) -> Bytes[4]:
    return extcall f.foo([1, 2, 3])
    """
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    compile_code(code, input_bundle=input_bundle)


def test_annotation_size_interface_file_fail(make_input_bundle):
    ifoo = """
@external
def foo(a: uint256[K + 1]):
    ...

K: constant(uint8) = 255
    """
    code = """
import ifoo
    """
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    with pytest.raises(TypeMismatch):
        compile_code(code, input_bundle=input_bundle)
