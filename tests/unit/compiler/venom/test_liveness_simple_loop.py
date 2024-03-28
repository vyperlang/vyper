import vyper
from vyper.compiler.settings import Settings

source = """
@external
def foo(a: uint256):
    _numBids: uint256 = 20
    b: uint256 = 10

    for i: uint256 in range(128):
        b = 1 + _numBids
"""


def test_liveness_simple_loop():
    vyper.compile_code(source, ["opcodes"], settings=Settings(experimental_codegen=True))
