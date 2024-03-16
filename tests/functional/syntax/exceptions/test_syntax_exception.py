import pytest

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
def test_syntax_exception(assert_compile_failed, get_contract, bad_code):
    assert_compile_failed(lambda: get_contract(bad_code), SyntaxException)
