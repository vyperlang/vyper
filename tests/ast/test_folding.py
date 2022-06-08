import pytest

from vyper import ast as vy_ast
from vyper.ast import folding
from vyper.codegen.types import INTEGER_TYPES, parse_integer_typeinfo
from vyper.exceptions import OverflowException, TypeMismatch
from vyper.semantics import validate_semantics
from vyper.utils import SizeLimits


def test_integration():
    test_code = """
@external
def foo():
    a: uint256 = [1+2, 6+7][8-8]
    """

    expected_code = """
@external
def foo():
    a: uint256 = 3
    """
    test_ast = vy_ast.parse_to_ast(test_code)
    validate_semantics(test_ast, None)
    expected_ast = vy_ast.parse_to_ast(expected_code)
    validate_semantics(expected_ast, None)

    folding.fold(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_simple():
    test_code = """
@external
def foo():
    a: uint256 = 1 + 2
    """

    expected_code = """
@external
def foo():
    a: uint256 = 3
    """
    test_ast = vy_ast.parse_to_ast(test_code)
    validate_semantics(test_ast, None)
    expected_ast = vy_ast.parse_to_ast(expected_code)
    validate_semantics(expected_ast, None)

    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


def test_replace_binop_nested():
    test_code = """
@external
def foo():
    a: uint256 = ((6 + (2**4)) * 4) / 2
    """

    expected_code = """
@external
def foo():
    a: uint256 = 44
    """
    test_ast = vy_ast.parse_to_ast(test_code)
    validate_semantics(test_ast, None)
    expected_ast = vy_ast.parse_to_ast(expected_code)
    validate_semantics(expected_ast, None)

    folding.replace_literal_ops(test_ast)

    assert vy_ast.compare_nodes(test_ast, expected_ast)


@pytest.mark.parametrize(
    "typ,expr",
    [
        ("uint256", "2**255 * 2 / 10"),
        ("int256", "-2**255 * 2 - 10 + 100"),
    ],
)
def test_replace_int_bounds_fail(get_contract, assert_compile_failed, typ, expr):
    code = f"""
@external
def foo():
    a: {typ} = {expr}
    """
    assert_compile_failed(lambda: get_contract(code), OverflowException)


@pytest.mark.parametrize(
    "expr",
    [
        "18707220957835557353007165858768422651595.9365500927 + 1e-10 - 1e-10",
        "-18707220957835557353007165858768422651595.9365500928 - 1e-10 + 1e-10",
    ],
)
def test_replace_decimal_fail(get_contract, assert_compile_failed, expr):
    code = f"""
@external
def foo():
    a: decimal = {expr}
    """
    assert_compile_failed(lambda: get_contract(code), OverflowException)


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
    "MAX_INT128",
    "foo = MAX_INT128",
    "foo: int128[MAX_INT128] = 42",
    "foo = [MAX_INT128]",
    "def foo(bar: int128 = MAX_INT128): pass",
    "def foo(): bar = MAX_INT128",
    "def foo(): return MAX_INT128",
    "log foo(MAX_INT128)",
    "log foo(42, MAX_INT128)",
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
    "log MAX_INT128(42)",
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


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "%", "**"])
@pytest.mark.parametrize("constant_type", sorted(INTEGER_TYPES))
@pytest.mark.parametrize("return_type", sorted(INTEGER_TYPES))
@pytest.mark.fuzzing
def test_replace_constant_fail(
    get_contract_with_gas_estimation, assert_compile_failed, op, constant_type, return_type
):
    c1 = f"""
a: constant({constant_type}) = 2

@external
def foo() -> {return_type}:
    return a {op} 2
    """

    c2 = f"""
a: constant({constant_type}) = 2
b: constant({return_type}) = 1

@external
def foo() -> {return_type}:
    return a + b
    """

    if constant_type != return_type:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c1), TypeMismatch)
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c2), TypeMismatch)


@pytest.mark.parametrize(
    "return_type,bounds", [(t, parse_integer_typeinfo(t).bounds) for t in sorted(INTEGER_TYPES)]
)
def test_replace_constant_overflow(
    get_contract_with_gas_estimation, assert_compile_failed, return_type, bounds
):
    lo = bounds[0]
    hi = bounds[1]

    c1 = f"""
a: constant({return_type}) = {hi}
b: constant({return_type}) = 1

@external
def foo() -> {return_type}:
    return b + a
    """

    c2 = f"""
a: constant({return_type}) = {lo}
b: constant({return_type}) = 1

@external
def foo() -> {return_type}:
    return a - b
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(c1), OverflowException)
    assert_compile_failed(lambda: get_contract_with_gas_estimation(c2), OverflowException)


@pytest.mark.parametrize("op", ["<", "<=", "==", "!=", ">", ">="])
@pytest.mark.parametrize(
    "constant_type,bounds", [(t, parse_integer_typeinfo(t).bounds) for t in sorted(INTEGER_TYPES)]
)
@pytest.mark.fuzzing
def test_replace_compare_constant_overflow(
    get_contract_with_gas_estimation, assert_compile_failed, op, constant_type, bounds
):
    lo = bounds[0]
    hi = bounds[1]

    c1 = f"""
a: constant({constant_type}) = 2

@external
def foo() -> bool:
    return a {op} {hi + 1}
    """

    c2 = f"""
a: constant({constant_type}) = 2

@external
def foo() -> bool:
    return {lo - 1} {op} a
    """

    if not hi + 1 <= SizeLimits.MAX_UINT256:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c1), OverflowException)
    else:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c1), TypeMismatch)

    if not lo - 1 >= SizeLimits.MIN_INT256:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c2), OverflowException)
    else:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c2), TypeMismatch)


@pytest.mark.parametrize("op", ["<", "<=", "==", "!=", ">", ">="])
@pytest.mark.parametrize("constant_type_1", sorted(INTEGER_TYPES))
@pytest.mark.parametrize("constant_type_2", sorted(INTEGER_TYPES))
@pytest.mark.fuzzing
def test_replace_compare_constant_type_mismatch(
    get_contract_with_gas_estimation, assert_compile_failed, op, constant_type_1, constant_type_2
):
    c = f"""
a: constant({constant_type_1}) = 2
b: constant({constant_type_2}) = 1

@external
def foo() -> bool:
    return a {op} b
    """

    if constant_type_1 != constant_type_2:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(c), TypeMismatch)
