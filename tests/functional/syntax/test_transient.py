import pytest

from vyper import compile_code
from vyper.exceptions import StateAccessViolation

fail_list = [
    (
        """
x: transient(uint256)

@external
@pure
def foo() -> uint256:
    return self.x
    """,
        StateAccessViolation,
    )
]


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_compilation_fails_with_exception(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)
