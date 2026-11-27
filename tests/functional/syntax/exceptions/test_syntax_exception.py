import pytest

from vyper.compiler import compile_code
from vyper.exceptions import SyntaxException

fail_list = [
    """
x: Bytes[1:3]
    """,
    """
b: int128[int128: address]
    """,
    """
x: int128[5]
@external
def foo():
    self.x[2:4] = 3
    """,
    """
x: int128[5]
@external
def foo():
    z = self.x[2:4]
    """,
    """
@external
def foo():
    x: int128[5]
    z = x[2:4]
    """,
    """
Transfer: event({_rom&: indexed(address)})
    """,
    """
@external
def test() -> uint256:
    for i in range(0, 4):
      return 0
    else:
      return 1
    return 1
    """,
    """
@external
def foo():
    x = y = 3
    """,
    """
@external
def foo():
    x: address = create_minimal_proxy_to(0x123456789012345678901234567890123456789)
    """,
    """
@external
def foo():
    x: Bytes[4] = raw_call(0x123456789012345678901234567890123456789, "cow", max_outsize=4)
    """,
    """
@external
def foo():
    x: address = 0x12345678901234567890123456789012345678901
    """,
    """
@external
def foo():
    x: address = 0x01234567890123456789012345678901234567890
    """,
    """
@external
def foo():
    x: address = 0x123456789012345678901234567890123456789
    """,
    """
a: internal(uint256)
    """,
    """
@external
def foo():
    x: uint256 = +1  # test UAdd ast blocked
    """,
    """
@internal
def f(a:uint256,/):  # test posonlyargs blocked
    return

@external
def g():
    self.f()
    """,
    """
@external
def foo():
    for i in range(0, 10):
        pass
    """,
    """
@external
def foo():
    for i: $$$ in range(0, 10):
        pass
    """,
    """
struct S:
    x: int128
s: S = S(x=int128, 1)
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_syntax_exception(bad_code):
    with pytest.raises(SyntaxException):
        compile_code(bad_code)


def test_bad_staticcall_keyword():
    bad_code = """
from ethereum.ercs import IERC20Detailed

def foo():
    staticcall ERC20(msg.sender).transfer(msg.sender, staticall IERC20Detailed(msg.sender).decimals())
    """  # noqa
    with pytest.raises(SyntaxException) as e:
        compile_code(bad_code)

    expected_error = """
invalid syntax. Perhaps you forgot a comma?

  contract "<unknown>:5", line 5:54 
       4 def foo():
  ---> 5     staticcall ERC20(msg.sender).transfer(msg.sender, staticall IERC20Detailed(msg.sender).decimals())
  -------------------------------------------------------------^
       6

  (hint: did you mean `staticcall`?)
    """  # noqa
    assert str(e.value) == expected_error.strip()


@pytest.mark.parametrize(
    "bad_literal",
    [
        # Trailing underscores
        "123_",
        "0x123_",
        "0b10101010_",
        "0o123_",
        "123.45_",
        # Double underscores
        "10__0",
        "0x12__34",
        "0b10101010__10101010",
        "0o12__34",
        "12.34__56",
    ],
)
def test_invalid_numeric_literal_underscores(bad_literal):
    code = f"""
@external
def foo():
    x = {bad_literal}
    """
    with pytest.raises(SyntaxException):
        compile_code(code)


@pytest.mark.parametrize("bad_name", ["foo-test", "foo.bar", "foo$", "1foo"])
def test_invalid_function_name(bad_name):
    code = f"""
@external
@pure
def {bad_name}() -> uint256:
    return 1
    """
    with pytest.raises(SyntaxException) as e:
        compile_code(code)

    assert e.value.message == f"invalid function name `{bad_name}`"
    assert e.value.hint == (
        "function names can only contain letters, digits and underscores, "
        "and cannot start with a digit"
    )


def test_missing_parentheses_is_not_an_invalid_function_name():
    code = """
@external
def foo -> uint256:
    return 1
    """
    with pytest.raises(SyntaxException) as e:
        compile_code(code)

    assert "invalid function name" not in e.value.message
    assert e.value.hint is None
