import pytest

from vyper import compiler
from vyper.exceptions import NamespaceCollision

fail_list = [
    """
@external
def foo(int128: int128):
    pass
    """,
    """
@external
def foo():
    x: int128 = 12
@external
def foo():
    y: int128 = 12
    """,
    """
foo: int128

@external
def foo():
    pass
    """,
    """
x: int128
x: int128
    """,
    """
@external
def foo():
    x: int128 = 0
    x: int128 = 0
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_insufficient_arguments(bad_code):
    with pytest.raises(NamespaceCollision):
        compiler.compile_code(bad_code)


def test_builtin_name_collision():
    code = """
@external
def foo():
    msg: bool = True
    """
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code)
    assert excinfo.value.message == "'msg' is already the name of a built-in"


def test_builtin_type_collision():
    code = """
int128: Bytes[3]
    """
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code)
    assert excinfo.value.message == "'int128' is already the name of a built-in"


def test_import_alias_collision_is_not_reported_as_builtin(make_input_bundle):
    code = """
import lib1 as lib
import lib2 as lib
    """
    input_bundle = make_input_bundle({"lib1.vy": "", "lib2.vy": ""})
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code, input_bundle=input_bundle)
    assert excinfo.value.message == "'lib' has already been declared"


def test_flag_collision_is_not_reported_as_builtin():
    code = """
flag Foo:
    A
    B

flag Foo:
    C
    D
    """
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code)
    assert excinfo.value.message == "'Foo' has already been declared"


def test_struct_collision_is_not_reported_as_builtin():
    code = """
struct Foo:
    x: uint256

struct Foo:
    y: uint256
    """
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code)
    assert excinfo.value.message == "'Foo' has already been declared"


pass_list = [
    """
x: int128

@external
def foo(x: int128): pass
    """,
    """
x: int128

@external
def foo():
    x: int128 = 1234
    """,
]


@pytest.mark.parametrize("code", pass_list)
def test_valid(code):
    compiler.compile_code(code)
