import pytest

from vyper import (
    ast as vy_ast,
)
from vyper.ast import (
    folding,
)


def test_integration():
    test_ast = vy_ast.parse_to_ast("[1+2, 6+7][8-8]")
    expected_ast = vy_ast.parse_to_ast("3")

    folding.fold(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_simple():
    test_ast = vy_ast.parse_to_ast("1 + 2")
    expected_ast = vy_ast.parse_to_ast("3")

    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_nested():
    test_ast = vy_ast.parse_to_ast("((6 + (2**4)) * 4) / 2")
    expected_ast = vy_ast.parse_to_ast("44")

    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_literal_ops():
    test_ast = vy_ast.parse_to_ast("[not True, True and False, True or False]")
    expected_ast = vy_ast.parse_to_ast("[False, False, True]")

    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_subscripts_simple():
    test_ast = vy_ast.parse_to_ast("[foo, bar, baz][1]")
    expected_ast = vy_ast.parse_to_ast("bar")

    folding.replace_subscripts(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_subscripts_nested():
    test_ast = vy_ast.parse_to_ast("[[0, 1], [2, 3], [4, 5]][2][1]")
    expected_ast = vy_ast.parse_to_ast("5")

    folding.replace_subscripts(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


constants_modified = [
    "bar = FOO",
    "bar: int128[FOO]",
    "[1, 2, FOO]",
    "def bar(a: int128 = FOO): pass",
    "log.bar({bar: FOO})",
    "FOO + 1",
]


@pytest.mark.parametrize("source", constants_modified)
def test_replace_constant(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_constant(folded_ast, "FOO", vy_ast.Int(value=31337))

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


constants_unmodified = [
    "FOO = 42",
    "self.FOO = 42",
    "bar = FOO()",
    "FOO()",
    "bar = FOO()",
    "bar = self.FOO",
    "log.bar({FOO: bar})",
    "[1, 2, FOO()]",
]


@pytest.mark.parametrize("source", constants_unmodified)
def test_replace_constant_no(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_constant(folded_ast, "FOO", vy_ast.Int(value=31337))

    assert vy_ast.compare_nodes(unmodified_ast, folded_ast)


builtins_modified = [
    "MAX_INT128",
    "foo = MAX_INT128",
    "foo: int128[MAX_INT128] = 42",
    "foo = [MAX_INT128]",
    "def foo(bar: int128 = MAX_INT128): pass",
    "def foo(): bar = MAX_INT128",
    "def foo(): return MAX_INT128",
]


@pytest.mark.parametrize("source", builtins_modified)
def test_replace_builtin_constant(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_builtin_constants(folded_ast)

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


builtins_unmodified = [
    "MAX_INT128 = 2",
    "MAX_INT128()",
    "def foo(MAX_INT128: int128 = 42): pass",
    "def foo(): MAX_INT128 = 42",
    "def MAX_INT128(): pass",
]


@pytest.mark.parametrize("source", builtins_unmodified)
def test_replace_builtin_constant_no(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_builtin_constants(folded_ast)

    assert vy_ast.compare_nodes(unmodified_ast, folded_ast)


userdefined_modified = [
    "FOO",
    "foo = FOO",
    "foo: int128[FOO] = 42",
    "foo = [FOO]",
    "foo += FOO",
    "def foo(bar: int128 = FOO): pass",
    "def foo(): bar = FOO",
    "def foo(): return FOO",
]


@pytest.mark.parametrize("source", userdefined_modified)
def test_replace_userdefined_constant(source):
    source = f"FOO: constant(int128) = 42\n{source}"

    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_user_defined_constants(folded_ast)

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


userdefined_unmodified = [
    "FOO: constant(int128) = 42",
    "FOO = 42",
    "FOO += 42",
    "FOO()",
    "def foo(FOO: int128 = 42): pass",
    "def foo(): FOO = 42",
    "def FOO(): pass",
]


@pytest.mark.parametrize("source", userdefined_unmodified)
def test_replace_userdefined_constant_no(source):
    source = f"FOO: constant(int128) = 42\n{source}"

    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_user_defined_constants(folded_ast)

    assert vy_ast.compare_nodes(unmodified_ast, folded_ast)
