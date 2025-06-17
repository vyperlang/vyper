from pytest import raises

from vyper import compile_code
from vyper.exceptions import SyntaxException, VyperException


def test_type_exception_pos():
    pos = (1, 2)

    with raises(VyperException) as e:
        raise VyperException("Fail!", pos)

    assert e.value.lineno == 1
    assert e.value.col_offset == 2
    assert str(e.value) == "line 1:2 Fail!"


# multiple exceptions in file
def test_multiple_exceptions(get_contract, assert_compile_failed):
    code = """
struct A:
    b: B  # unknown type

foo: immutable(uint256)
bar: immutable(uint256)
@deploy
def __init__():
    self.foo = 1  # SyntaxException
    self.bar = 2  # SyntaxException

    """
    assert_compile_failed(lambda: get_contract(code), VyperException)


def test_exception_contains_file(make_input_bundle):
    code = """
def bar()>:
    """
    input_bundle = make_input_bundle({"code.vy": code})
    with raises(SyntaxException, match="contract"):
        compile_code(code, input_bundle=input_bundle)


def test_exception_reports_correct_file(make_input_bundle, chdir_tmp_path):
    code_a = "def bar()>:"
    code_b = "import A"
    input_bundle = make_input_bundle({"A.vy": code_a, "B.vy": code_b})

    with raises(SyntaxException, match=r'contract "A\.vy:\d+"'):
        compile_code(code_b, input_bundle=input_bundle)


def test_syntax_exception_reports_correct_offset(make_input_bundle):
    code = """
def foo():
    uint256 a = pass
    """
    input_bundle = make_input_bundle({"code.vy": code})

    with raises(SyntaxException, match=r"line \d+:12"):
        compile_code(code, input_bundle=input_bundle)
