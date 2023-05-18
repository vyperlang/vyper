import pytest

from vyper import ast as vy_ast
from vyper.ast import folding
from vyper.exceptions import OverflowException


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


def test_replace_binop_nested_intermediate_overflow():
    test_ast = vy_ast.parse_to_ast("2**255 * 2 / 10")
    with pytest.raises(OverflowException):
        folding.fold(test_ast)


def test_replace_binop_nested_intermediate_underflow():
    test_ast = vy_ast.parse_to_ast("-2**255 * 2 - 10 + 100")
    with pytest.raises(OverflowException):
        folding.fold(test_ast)


def test_replace_decimal_nested_intermediate_overflow():
    test_ast = vy_ast.parse_to_ast(
        "18707220957835557353007165858768422651595.9365500927 + 1e-10 - 1e-10"
    )
    with pytest.raises(OverflowException):
        folding.fold(test_ast)


def test_replace_decimal_nested_intermediate_underflow():
    test_ast = vy_ast.parse_to_ast(
        "-18707220957835557353007165858768422651595.9365500928 - 1e-10 + 1e-10"
    )
    with pytest.raises(OverflowException):
        folding.fold(test_ast)


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
    "log bar(FOO)",
    "FOO + 1",
    "a: int128[FOO / 2]",
    "a[FOO - 1] = 44",
]


@pytest.mark.parametrize("source", constants_modified)
def test_replace_constant(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_constant(folded_ast, "FOO", vy_ast.Int(value=31337), True)

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


constants_unmodified = [
    "FOO = 42",
    "self.FOO = 42",
    "bar = FOO()",
    "FOO()",
    "bar = FOO()",
    "bar = self.FOO",
    "log FOO(bar)",
    "[1, 2, FOO()]",
    "FOO[42] = 2",
]


@pytest.mark.parametrize("source", constants_unmodified)
def test_replace_constant_no(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_constant(folded_ast, "FOO", vy_ast.Int(value=31337), True)

    assert vy_ast.compare_nodes(unmodified_ast, folded_ast)


builtins_modified = [
    "ZERO_ADDRESS",
    "foo = ZERO_ADDRESS",
    "foo: int128[ZERO_ADDRESS] = 42",
    "foo = [ZERO_ADDRESS]",
    "def foo(bar: address = ZERO_ADDRESS): pass",
    "def foo(): bar = ZERO_ADDRESS",
    "def foo(): return ZERO_ADDRESS",
    "log foo(ZERO_ADDRESS)",
    "log foo(42, ZERO_ADDRESS)",
]


@pytest.mark.parametrize("source", builtins_modified)
def test_replace_builtin_constant(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    folding.replace_builtin_constants(folded_ast)

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


builtins_unmodified = [
    "ZERO_ADDRESS = 2",
    "ZERO_ADDRESS()",
    "def foo(ZERO_ADDRESS: int128 = 42): pass",
    "def foo(): ZERO_ADDRESS = 42",
    "def ZERO_ADDRESS(): pass",
    "log ZERO_ADDRESS(42)",
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


dummy_address = "0x000000000000000000000000000000000000dEaD"
userdefined_attributes = [("b: uint256 = ADDR.balance", f"b: uint256 = {dummy_address}.balance")]


@pytest.mark.parametrize("source", userdefined_attributes)
def test_replace_userdefined_attribute(source):
    preamble = f"ADDR: constant(address) = {dummy_address}"
    l_source = f"{preamble}\n{source[0]}"
    r_source = f"{preamble}\n{source[1]}"

    l_ast = vy_ast.parse_to_ast(l_source)
    folding.replace_user_defined_constants(l_ast)

    r_ast = vy_ast.parse_to_ast(r_source)

    assert vy_ast.compare_nodes(l_ast, r_ast)


userdefined_struct = [("b: Foo = FOO", "b: Foo = Foo({a: 123, b: 456})")]


@pytest.mark.parametrize("source", userdefined_struct)
def test_replace_userdefined_struct(source):
    preamble = """
struct Foo:
    a: uint256
    b: uint256

FOO: constant(Foo) = Foo({a: 123, b: 456})
    """
    l_source = f"{preamble}\n{source[0]}"
    r_source = f"{preamble}\n{source[1]}"

    l_ast = vy_ast.parse_to_ast(l_source)
    folding.replace_user_defined_constants(l_ast)

    r_ast = vy_ast.parse_to_ast(r_source)

    assert vy_ast.compare_nodes(l_ast, r_ast)


userdefined_nested_struct = [
    ("b: Foo = FOO", "b: Foo = Foo({f1: Bar({b1: 123, b2: 456}), f2: 789})")
]


@pytest.mark.parametrize("source", userdefined_nested_struct)
def test_replace_userdefined_nested_struct(source):
    preamble = """
struct Bar:
    b1: uint256
    b2: uint256

struct Foo:
    f1: Bar
    f2: uint256

FOO: constant(Foo) = Foo({f1: Bar({b1: 123, b2: 456}), f2: 789})
    """
    l_source = f"{preamble}\n{source[0]}"
    r_source = f"{preamble}\n{source[1]}"

    l_ast = vy_ast.parse_to_ast(l_source)
    folding.replace_user_defined_constants(l_ast)

    r_ast = vy_ast.parse_to_ast(r_source)

    assert vy_ast.compare_nodes(l_ast, r_ast)


builtin_folding_functions = [("ceil(4.2)", "5"), ("floor(4.2)", "4")]

builtin_folding_sources = [
    "{}",
    "foo = {}",
    "foo = [{0}, {0}]",
    "def foo(): {}",
    "def foo(): return {}",
    "def foo(bar: {}): pass",
]


@pytest.mark.parametrize("source", builtin_folding_sources)
@pytest.mark.parametrize("original,result", builtin_folding_functions)
def test_replace_builtins(source, original, result):
    original_ast = vy_ast.parse_to_ast(source.format(original))
    target_ast = vy_ast.parse_to_ast(source.format(result))

    folding.replace_builtin_functions(original_ast)

    assert vy_ast.compare_nodes(original_ast, target_ast)
