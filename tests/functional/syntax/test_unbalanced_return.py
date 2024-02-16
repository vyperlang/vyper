import pytest

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException, StructureException

fail_list = [
    (
        """
@external
def foo() -> int128:
    pass  # missing return
    """,
        FunctionDeclarationException,
    ),
    (
        """
@external
def foo() -> int128:
    if False:
        return 123
    # missing return
    """,
        FunctionDeclarationException,
    ),
    (
        """
@external
def test() -> int128:
    if 1 == 1 :
        return 1
        if True:  # unreachable
            return 0
    else:
        assert msg.sender != msg.sender
    """,
        StructureException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    selfdestruct(sender)
    return True  # unreachable
    """,
        StructureException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    selfdestruct(sender)
    a: address = sender  # unreachable
    """,
        StructureException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    if sender == empty(address):
        selfdestruct(sender)
        _sender: address = sender  # unreachable
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
    return True  # unreachable
    """,
        StructureException,
    ),
    (
        """
@internal
def foo() -> bool:
    raw_revert(b"vyper")
    x: uint256 = 3  # unreachable
    """,
        StructureException,
    ),
    (
        """
@internal
def foo(x: uint256) -> bool:
    if x == 2:
        raw_revert(b"vyper")
        a: uint256 = 3  # unreachable
    else:
        return False
    """,
        StructureException,
    ),
    (
        """
@internal
def foo():
    return
    return  # unreachable
    """,
        StructureException,
    ),
    (
        """
@internal
def foo() -> uint256:
    if block.number % 2 == 0:
        return 5
    elif block.number % 3 == 0:
        return 6
    else:
        return 10
    return 0  # unreachable
    """,
        StructureException,
    ),
    (
        """
@internal
def foo() -> uint256:
    for i: uint256 in range(10):
        if i == 11:
            return 1
        """,
        FunctionDeclarationException,
    ),
    (
        """
@internal
def foo() -> uint256:
    for i: uint256 in range(9):
        if i == 11:
            return 1
    if block.number % 2 == 0:
        return 1
        """,
        FunctionDeclarationException,
    ),
    (
        """
@internal
def foo() -> uint256:
    for i: uint256 in range(10):
        return 1
        pass  # unreachable
    return 5
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
    x: bytes32 = empty(bytes32)
    if False:
        if False:
            return 0
        else:
            x = keccak256(x)
            return 1
    else:
        x = keccak256(x)
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
    """
@external
def foo() -> int128:
    for i: uint256 in range(1):
        return 1
    return 0
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_return_success(good_code):
    assert compiler.compile_code(good_code) is not None
