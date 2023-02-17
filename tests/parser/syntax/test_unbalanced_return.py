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
def valid_address(sender: address) -> bool:
    if sender == ZERO_ADDRESS:
        pass
        return True
    else:
        return False
    return True
    """,
        StructureException,
    ),
    (
        """
@internal
def valid_address(sender: address) -> bool:
    if sender == ZERO_ADDRESS:
        return True
    elif sender != ZERO_ADDRESS:
        pass
        return False
    else:
        a: address = sender
        return False
    return True
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
]


@pytest.mark.parametrize("good_code", valid_list)
def test_return_success(good_code):
    assert compiler.compile_code(good_code) is not None
