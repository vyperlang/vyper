import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

fail_list = [
    """
@external
def foo(inp: Bytes[4]) -> int128:
    return len(inp)
    """,
    """
@external
def foo(inp: int128) -> uint256:
    return len(inp)
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):
    if isinstance(bad_code, tuple):
        with pytest.raises(bad_code[1]):
            compile_code(bad_code[0])
    else:
        with pytest.raises(TypeMismatch):
            compile_code(bad_code)


valid_list = [
    """
@external
def foo(inp: Bytes[10]) -> uint256:
    return len(inp)
    """,
    """
@external
def foo(inp: String[10]) -> uint256:
    return len(inp)
    """,
    """
BAR: constant(String[5]) = "vyper"
FOO: constant(uint256) = len(BAR)

@external
def foo() -> uint256:
    a: uint256 = FOO
    return a
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_list_success(good_code):
    assert compile_code(good_code) is not None


def test_len_type_mismatch_message_uses_readable_type_names():
    # `len()`'s accepted types must be shown by their user-facing names, not as
    # internal `GenericTypeAcceptor(<class ...>)` reprs. See issue #4955.
    code = """
@external
def foo(inp: int128) -> uint256:
    return len(inp)
    """
    with pytest.raises(TypeMismatch) as e:
        compile_code(code)

    assert e.value.message == (
        "Given reference has type int128, expected one of String, Bytes, DynArray"
    )


def test_index_type_mismatch_message_uses_readable_type_names():
    # Exercises the `_generic_id` fallback: `IntegerT` is parametric, so its
    # `_id` is a property with no value at the class level and the name comes
    # from `_generic_id` ("integer") instead.
    code = """
@external
def foo(x: DynArray[uint256, 3]) -> uint256:
    return x[b"ab"]
    """
    with pytest.raises(TypeMismatch) as e:
        compile_code(code)

    assert e.value.message == "Expected integer but literal can only be cast as Bytes[2]."
