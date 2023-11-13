import pytest

from vyper import ast as vy_ast
from vyper.ast import folding
from vyper.exceptions import OverflowException
from vyper.semantics import validate_semantics


def test_integration():
    test = """
@external
def foo():
    a: uint256 = [1+2, 6+7][8-8]
    """

    expected = """
@external
def foo():
    a: uint256 = 3
    """

    test_ast = vy_ast.parse_to_ast(test)
    expected_ast = vy_ast.parse_to_ast(expected)

    validate_semantics(test_ast, {})
    folding.fold(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_simple():
    test = """
@external
def foo():
    a: uint256 = 1 + 2
    """

    expected = """
@external
def foo():
    a: uint256 = 3
    """

    test_ast = vy_ast.parse_to_ast(test)
    expected_ast = vy_ast.parse_to_ast(expected)

    validate_semantics(test_ast, {})
    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_nested():
    test = """
@external
def foo():
    a: uint256 = ((6 + (2**4)) * 4) / 2
    """

    expected = """
@external
def foo():
    a: uint256 = 44
    """
    test_ast = vy_ast.parse_to_ast(test)
    expected_ast = vy_ast.parse_to_ast(expected)

    validate_semantics(test_ast, {})
    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_nested_intermediate_overflow():
    test = """
@external
def foo():
    a: uint256 = 2**255 * 2 / 10
    """
    test_ast = vy_ast.parse_to_ast(test)
    validate_semantics(test_ast, {})
    with pytest.raises(OverflowException):
        folding.replace_literal_ops(test_ast)


def test_replace_binop_nested_intermediate_underflow():
    test = """
@external
def foo():
    a: int256 = -2**255 * 2 - 10 + 100
    """
    test_ast = vy_ast.parse_to_ast(test)
    validate_semantics(test_ast, {})
    with pytest.raises(OverflowException):
        folding.replace_literal_ops(test_ast)


def test_replace_decimal_nested_intermediate_overflow():
    test = """
@external
def foo():
    a: decimal = 18707220957835557353007165858768422651595.9365500927 + 1e-10 - 1e-10
    """
    test_ast = vy_ast.parse_to_ast(test)
    validate_semantics(test_ast, {})
    with pytest.raises(OverflowException):
        folding.replace_literal_ops(test_ast)


def test_replace_decimal_nested_intermediate_underflow():
    test = """
@external
def foo():
    a: decimal = -18707220957835557353007165858768422651595.9365500928 - 1e-10 + 1e-10
    """
    test_ast = vy_ast.parse_to_ast(test)
    validate_semantics(test_ast, {})
    with pytest.raises(OverflowException):
        folding.replace_literal_ops(test_ast)


def test_replace_literal_ops():
    test = """
@external
def foo():
    a: bool[3] = [not True, True and False, True or False]
    """

    expected = """
@external
def foo():
    a: bool[3] = [False, False, True]
    """
    test_ast = vy_ast.parse_to_ast(test)
    expected_ast = vy_ast.parse_to_ast(expected)

    validate_semantics(test_ast, {})
    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_subscripts_simple():
    test = """
@external
def foo():
    a: uint256 = [1, 2, 3][1]
    """

    expected = """
@external
def foo():
    a: uint256 = 2
    """
    test_ast = vy_ast.parse_to_ast(test)
    expected_ast = vy_ast.parse_to_ast(expected)

    validate_semantics(test_ast, {})
    folding.replace_subscripts(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_subscripts_nested():
    test = """
@external
def foo():
    a: uint256 = [[0, 1], [2, 3], [4, 5]][2][1]
    """

    expected = """
@external
def foo():
    a: uint256 = 5
    """
    test_ast = vy_ast.parse_to_ast(test)
    expected_ast = vy_ast.parse_to_ast(expected)

    validate_semantics(test_ast, {})
    folding.replace_subscripts(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


constants_modified = [
    """
FOO: constant(uint256) = 4

@external
def foo():
    bar: uint256 = 1
    bar = FOO
    """,
    """
FOO: constant(uint256) = 4
bar: int128[FOO]
    """,
    """
FOO: constant(uint256) = 4

@external
def foo():
    a: uint256[3] = [1, 2, FOO]
    """,
    """
FOO: constant(uint256) = 4
@external
def bar(a: uint256 = FOO):
    pass
    """,
    """
FOO: constant(uint256) = 4

event bar:
    a: uint256

@external
def foo():
    log bar(FOO)
    """,
    """
FOO: constant(uint256) = 4

@external
def foo():
    a: uint256 = FOO + 1
    """,
    """
FOO: constant(uint256) = 4

@external
def foo():
    a: int128[FOO / 2] = [1, 2]
    """,
    """
FOO: constant(uint256) = 4

@external
def bar(x: DynArray[uint256, 4]):
    a: DynArray[uint256, 4] = x
    a[FOO - 1] = 44
    """,
]


@pytest.mark.parametrize("source", constants_modified)
def test_replace_constant(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    validate_semantics(folded_ast, {})
    folding.replace_user_defined_constants(folded_ast)

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


constants_unmodified = [
    """
FOO: immutable(uint256)

@external
def __init__():
    FOO = 42
    """,
    """
FOO: uint256

@external
def foo():
    self.FOO = 42
    """,
    """
bar: uint256

@internal
def FOO() -> uint256:
    return 123

@external
def foo():
    bar: uint256 = 456
    bar = self.FOO()
    """,
    """
@internal
def FOO():
    pass

@external
def foo():
    self.FOO()
    """,
    """
FOO: uint256

@external
def foo():
    bar: uint256 = 1
    bar = self.FOO
    """,
    """
event FOO:
    a: uint256

@external
def foo(bar: uint256):
    log FOO(bar)
    """,
    """
@internal
def FOO() -> uint256:
    return 3

@external
def foo():
    a: uint256[3] = [1, 2, self.FOO()]
    """,
    """
@external
def foo():
    FOO: DynArray[uint256, 5] = [1, 2, 3, 4, 5]
    FOO[4] = 2
    """,
]


@pytest.mark.parametrize("source", constants_unmodified)
def test_replace_constant_no(source):
    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    validate_semantics(folded_ast, {})
    folding.replace_user_defined_constants(folded_ast)

    assert vy_ast.compare_nodes(unmodified_ast, folded_ast)


userdefined_modified = [
    """
@external
def foo():
    foo: int128 = FOO
    """,
    """
@external
def foo():
    foo: DynArray[int128, FOO] = []
    """,
    """
@external
def foo():
    foo: int128[1] = [FOO]
    """,
    """
@external
def foo():
    foo: int128 = 3
    foo += FOO
    """,
    """
@external
def foo(bar: int128 = FOO):
    pass
    """,
    """
@external
def foo() -> int128:
    return FOO
    """,
]


@pytest.mark.parametrize("source", userdefined_modified)
def test_replace_userdefined_constant(source):
    source = f"FOO: constant(int128) = 42\n{source}"

    unmodified_ast = vy_ast.parse_to_ast(source)
    folded_ast = vy_ast.parse_to_ast(source)

    validate_semantics(folded_ast, {})
    folding.replace_user_defined_constants(folded_ast)

    assert not vy_ast.compare_nodes(unmodified_ast, folded_ast)


dummy_address = "0x000000000000000000000000000000000000dEaD"
userdefined_attributes = [
    (
        """
@external
def foo():
    b: uint256 = ADDR.balance
    """,
        f"""
@external
def foo():
    b: uint256 = {dummy_address}.balance
    """,
    )
]


@pytest.mark.parametrize("source", userdefined_attributes)
def test_replace_userdefined_attribute(source):
    preamble = f"ADDR: constant(address) = {dummy_address}"
    l_source = f"{preamble}\n{source[0]}"
    r_source = f"{preamble}\n{source[1]}"

    l_ast = vy_ast.parse_to_ast(l_source)
    validate_semantics(l_ast, {})
    folding.replace_user_defined_constants(l_ast)

    r_ast = vy_ast.parse_to_ast(r_source)

    assert vy_ast.compare_nodes(l_ast, r_ast)


userdefined_struct = [
    (
        """
@external
def foo():
    b: Foo = FOO
    """,
        """
@external
def foo():
    b: Foo = Foo({a: 123, b: 456})
    """,
    )
]


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
    validate_semantics(l_ast, {})
    folding.replace_user_defined_constants(l_ast)

    r_ast = vy_ast.parse_to_ast(r_source)

    assert vy_ast.compare_nodes(l_ast, r_ast)


userdefined_nested_struct = [
    (
        """
@external
def foo():
    b: Foo = FOO
    """,
        """
@external
def foo():
    b: Foo = Foo({f1: Bar({b1: 123, b2: 456}), f2: 789})
    """,
    )
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
    validate_semantics(l_ast, {})
    folding.replace_user_defined_constants(l_ast)

    r_ast = vy_ast.parse_to_ast(r_source)

    assert vy_ast.compare_nodes(l_ast, r_ast)


builtin_folding_functions = [("ceil(4.2)", "5"), ("floor(4.2)", "4")]

builtin_folding_sources = [
    """
@external
def foo():
    foo: int256 = {}
    """,
    """
foo: constant(int256[2]) = [{0}, {0}]
    """,
    """
@external
def foo() -> int256:
    return {}
    """,
    """
@external
def foo(bar: int256 = {}):
    pass
    """,
]


@pytest.mark.parametrize("source", builtin_folding_sources)
@pytest.mark.parametrize("original,result", builtin_folding_functions)
def test_replace_builtins(source, original, result):
    original_ast = vy_ast.parse_to_ast(source.format(original))
    target_ast = vy_ast.parse_to_ast(source.format(result))

    validate_semantics(original_ast, {})
    folding.replace_builtin_functions(original_ast)

    assert vy_ast.compare_nodes(original_ast, target_ast)
