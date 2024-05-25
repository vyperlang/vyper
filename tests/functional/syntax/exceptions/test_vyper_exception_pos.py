from pytest import raises

from vyper.exceptions import VyperException


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
