import pytest

from vyper import compiler
from vyper.compiler.settings import Settings
from vyper.utils import method_id_int

valid_list = [
    """
@external
def foo(x: uint256):
    print(x)
    """,
    """
@external
def foo(x: Bytes[1]):
    print(x)
    """,
    """
struct Foo:
    x: Bytes[128]
@external
def foo(foo: Foo):
    print(foo)
    """,
    """
struct Foo:
    x: uint256
@external
def foo(foo: Foo):
    print(foo)
    """,
    """
BAR: constant(DynArray[uint256, 5]) = [1, 2, 3, 4, 5]

@external
def foo():
    print(BAR)
    """,
    """
FOO: constant(uint256) = 1
BAR: constant(DynArray[uint256, 5]) = [1, 2, 3, 4, 5]

@external
def foo():
    print(FOO, BAR)
    """,
    # Regression test: print with storage struct (ctx.unwrap fix)
    """
struct Foo:
    x: uint256
    y: address

data: Foo

@external
def foo():
    self.data = Foo(x=42, y=msg.sender)
    print(self.data)
    """,
    # Regression test: print with storage bytes
    """
data: Bytes[128]

@external
def foo():
    self.data = b"hello world"
    print(self.data)
    """,
    # Regression test: print with storage string
    """
message: String[64]

@external
def foo():
    self.message = "test message"
    print(self.message)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_print_syntax(good_code):
    assert compiler.compile_code(good_code) is not None


def test_print_folded_hardhat_compat_kwarg():
    code = """
HARDHAT_COMPAT: constant(bool) = True

@external
def foo(x: uint256):
    print(x, hardhat_compat=HARDHAT_COMPAT)
    """

    out = compiler.compile_code(
        code, output_formats=["ir_runtime"], settings=Settings(experimental_codegen=True)
    )
    ir_runtime = str(out["ir_runtime"])

    assert f"0x{method_id_int('log(uint256)'):08x}" in ir_runtime
    assert f"0x{method_id_int('log(string,bytes)'):08x}" not in ir_runtime
