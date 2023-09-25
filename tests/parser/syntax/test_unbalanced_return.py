import pytest

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException, StructureException

fail_list = [
    (
        """
@external
def foo() -> int128:
    pass
    """,
        FunctionDeclarationException,
    ),
    (
        """
@external
def foo() -> int128:
    if False:
        return 123
    """,
        FunctionDeclarationException,
    ),
    (
        """
@external
def test() -> int128:
    if 1 == 1 :
        return 1
        if True:
            return 0
    else:
        assert msg.sender != msg.sender
    """,
        FunctionDeclarationException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    selfdestruct(sender)
    return True
    """,
        StructureException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    selfdestruct(sender)
    a: address = sender
    """,
        StructureException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    if sender == ZERO_ADDRESS:
        selfdestruct(sender)
        _sender: address = sender
    else:
        return False
    """,
        StructureException,
    ),
    (
        """
@internal
def foo() -> bool:
    raw_revert(b"vyper")
    return True
    """,
        StructureException,
    ),
    (
        """
@internal
def foo() -> bool:
    raw_revert(b"vyper")
    x: uint256 = 3
    """,
        StructureException,
    ),
    (
        """
@internal
def foo(x: uint256) -> bool:
    if x == 2:
        raw_revert(b"vyper")
        a: uint256 = 3
    else:
        return False
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_return_mismatch(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo() -> int128:
    return 123
    """,
    """
@external
def foo() -> int128:
    if True:
        return 123
    else:
        raise "test"
    """,
    """
@external
def foo() -> int128:
    if False:
        return 123
    else:
        selfdestruct(msg.sender)
    """,
    """
@external
def foo() -> int128:
    if False:
        return 123
    return 333
    """,
    """
@external
def test() -> int128:
    if 1 == 1 :
        return 1
    else:
        assert msg.sender != msg.sender
        return 0
    """,
    """
@external
def test() -> int128:
    x: bytes32 = EMPTY_BYTES32
    if False:
        if False:
            return 0
        else:
            x = keccak256(x)
            return 1
    else:
        x = keccak256(x)
        return 1
    return 1
    """,
    """
@external
def foo() -> int128:
    if True:
        return 123
    else:
        raw_revert(b"vyper")
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_return_success(good_code):
    assert compiler.compile_code(good_code) is not None
