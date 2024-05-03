import random

import pytest

from vyper import compiler

valid_list = [
    """
@external
@view
def foo() -> bytes32:
    return blobhash(0)
    """,
    """
@external
@view
def foo() -> bytes32:
    a: bytes32 = 0x0000000000000000000000000000000000000000000000000000000000000005
    a = blobhash(2)
    return a
    """,
    """
@external
@view
def foo() -> bytes32:
    a: bytes32 = blobhash(0)
    assert a != empty(bytes32)
    return a
    """,
    """
@external
@view
def foo() -> bytes32:
    a: bytes32 = blobhash(1337)
    assert a == empty(bytes32)
    return a
    """,
]


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("good_code", valid_list)
def test_blobhash_success(good_code):
    assert compiler.compile_code(good_code) is not None
    assembly = compiler.compile_code(good_code, output_formats=["asm"])["asm"].split(" ")
    assert "BLOBHASH" in assembly


@pytest.mark.requires_evm_version("cancun")
def test_get_blobhashes(env, get_contract, tx_failed):
    code = """
@external
def get_blobhash(i: uint256) -> bytes32:
    return blobhash(i)
"""
    c = get_contract(code)

    # mock the evm blobhash attribute
    env.blob_hashes = [random.randbytes(32) for _ in range(6)]

    for i in range(6):
        assert c.get_blobhash(i) == env.blob_hashes[i]

    assert c.get_blobhash(7) == b"\0" * 32
