import pytest

from vyper import ast as vy_ast
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


@pytest.mark.parametrize(
    "code, expected_message",
    [
        pytest.param(
            """
@external
def foo():
    msg: bool = True
    """,
            "'msg' is already the name of a built-in",
            id="builtin_name",
        ),
        pytest.param(
            """
int128: Bytes[3]
    """,
            "'int128' is already the name of a built-in",
            id="builtin_type",
        ),
        pytest.param(
            """
import lib1 as lib
import lib2 as lib
    """,
            "'lib' has already been declared",
            id="import_alias_is_not_a_builtin",
        ),
        pytest.param(
            """
flag Foo:
    A
    B

flag Foo:
    C
    D
    """,
            "'Foo' has already been declared",
            id="flag_is_not_a_builtin",
        ),
        pytest.param(
            """
struct Foo:
    x: uint256

struct Foo:
    y: uint256
    """,
            "'Foo' has already been declared",
            id="struct_is_not_a_builtin",
        ),
    ],
)
def test_collision_message(make_input_bundle, code, expected_message):
    input_bundle = make_input_bundle({"lib1.vy": "", "lib2.vy": ""})
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code, input_bundle=input_bundle)
    assert excinfo.value.message == expected_message


@pytest.mark.parametrize(
    "second_decl",
    [
        "import jsonabi2 as Foo",
        "import lib as Foo",
        "flag Foo:\n    A",
        "struct Foo:\n    x: uint256",
        "interface Foo:\n    def bar(): nonpayable",
        "Foo: uint256",
    ],
)
def test_collision_with_json_import_is_not_reported_as_builtin(make_input_bundle, second_decl):
    code = f"""
import jsonabi as Foo

{second_decl}
    """
    input_bundle = make_input_bundle({"jsonabi.json": "[]", "jsonabi2.json": "[]", "lib.vy": ""})
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code, input_bundle=input_bundle)
    assert excinfo.value.message == "'Foo' has already been declared"


def test_collision_with_vyi_import_points_at_the_import_stmt(make_input_bundle):
    # the alias is declared by the import statement, not by the imported file
    code = """
import ifacemod as Foo

flag Foo:
    A
    """
    input_bundle = make_input_bundle({"ifacemod.vyi": "@external\ndef bar(): ..."})
    with pytest.raises(NamespaceCollision) as excinfo:
        compiler.compile_code(code, input_bundle=input_bundle)
    assert excinfo.value.message == "'Foo' has already been declared"
    assert isinstance(excinfo.value.prev_decl, vy_ast.alias)


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
