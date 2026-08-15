import pytest

from vyper.compiler import compile_code
from vyper.exceptions import MemoryAllocationException


def test_memory_overflow():
    code = """
@external
def zzz(x: DynArray[uint256, 2**59]):  # 2**64 / 32 bytes per word == 2**59
    y: uint256[7] = [0,0,0,0,0,0,0]

    y[6] = y[5]
    """
    with pytest.raises(MemoryAllocationException):
        compile_code(code)
