import pytest

from vyper.exceptions import InvalidType, TypeMismatch

fail_list = [
    (
        """
@external
def foo() -> uint256:
    return extract32(b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(inp: address) -> int128:
    return extract32(inp, 0, output_type=int128)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> int128:
    b: int136 = 1
    return extract32(inp, b, output_type=int128)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> int128:
    b: int128 = -1
    return extract32(inp, b, output_type=int128)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> bool:
    return extract32(inp, 0, output_type=bool)
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_extract32_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):

    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
@external
def foo() -> uint256:
    return extract32(
        b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc",
        0,
        output_type=uint256
    )
    """,
    """
x: Bytes[100]
@external
def foo() -> uint256:
    self.x = b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 0, output_type=uint256)
    """,
    """
x: Bytes[100]
@external
def foo() -> uint256:
    self.x = b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 1, output_type=uint256)
""",
]


@pytest.mark.parametrize("good_code", valid_list)
def test_extract32_success(get_contract_with_gas_estimation, good_code):
    assert get_contract_with_gas_estimation(good_code) is not None
