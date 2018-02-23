from pytest import raises

from vyper import compiler
from vyper.exceptions import StructureException


def test_undef_toplevel():
    code = """
@public
def foo():
    x = bar(55)
    """
    with raises(StructureException) as ex:
        compiler.compile(code)
    assert "Not a top-level function: bar" in str(ex.value)


def test_undef_suggestion():
    code = """
@public
def bar(x: int128) -> int128:
    return 3 * x

@public
def foo() -> int128:
    return bar(20)
    """
    with raises(StructureException) as ex:
        compiler.compile(code)
    assert "Not a top-level function: bar" in str(ex.value)
    assert "Did you mean self.bar?" in str(ex.value)
