import pytest
from eth.codecs import abi


from vyper.compiler import compile_code
from vyper.exceptions import TypeMismatch


def test_buffer(get_contract, tx_failed):
    test_bytes = """
@external
def foo(x: Bytes[100]) -> ABIBuffer[100]:
    return convert(x, ABIBuffer[100])
    """

    c = get_contract(test_bytes)
    moo_result = c.foo(abi.encode("(bytes)", (b"cow",)))
    assert moo_result == b"cow"

