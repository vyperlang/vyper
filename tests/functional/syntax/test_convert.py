import pytest

from vyper import compile_code
from vyper.exceptions import InvalidType, StructureException, TypeMismatch

# conversion legality is checked at typechecking time, for all backends.
# compiling to an analysis-only output format proves the error comes from
# the frontend and not from one of the codegen pipelines.
ANALYSIS_ONLY = ["annotated_ast_dict"]

fail_list = [
    (  # narrowing integer -> bytesM
        """
@external
def foo(x: uint256) -> bytes1:
    return convert(x, bytes1)
    """,
        TypeMismatch,
    ),
    (  # signed integer -> address
        """
@external
def foo(x: int128) -> address:
    return convert(x, address)
    """,
        TypeMismatch,
    ),
    (  # address -> signed integer
        """
@external
def foo(x: address) -> int256:
    return convert(x, int256)
    """,
        TypeMismatch,
    ),
    (  # address -> decimal
        """
@external
def foo(x: address) -> decimal:
    return convert(x, decimal)
    """,
        TypeMismatch,
    ),
    (  # flag -> non-uint256 integer
        """
flag Foo:
    A
    B

@external
def foo(x: Foo) -> uint8:
    return convert(x, uint8)
    """,
        TypeMismatch,
    ),
    (  # non-uint256 integer -> flag
        """
flag Foo:
    A
    B

@external
def foo(x: uint8) -> Foo:
    return convert(x, Foo)
    """,
        TypeMismatch,
    ),
    (  # flag -> decimal
        """
flag Foo:
    A
    B

@external
def foo(x: Foo) -> decimal:
    return convert(x, decimal)
    """,
        TypeMismatch,
    ),
    (  # bytestring widening within the same class is not a conversion
        # (caught by the same-type check, which runs before the matrix)
        """
@external
def foo(x: Bytes[32]) -> Bytes[64]:
    return convert(x, Bytes[64])
    """,
        InvalidType,
    ),
    (  # decimal -> bool is allowed, but bool -> string is not
        """
@external
def foo(x: bool) -> String[32]:
    return convert(x, String[32])
    """,
        TypeMismatch,
    ),
    (  # unsupported target type
        """
@external
def foo(x: uint256) -> uint256[2]:
    return convert(x, uint256[2])
        """,
        StructureException,
    ),
    (  # typed constants are checked by declared type before codegen folding
        """
FOO: constant(uint256) = 1

@external
def foo() -> bytes1:
    return convert(FOO, bytes1)
        """,
        TypeMismatch,
    ),
    (  # exact same type
        """
@external
def foo(x: uint256) -> uint256:
    return convert(x, uint256)
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("code,exc", fail_list)
def test_convert_fail_at_typechecking(code, exc):
    with pytest.raises(exc):
        compile_code(code, output_formats=ANALYSIS_ONLY)


valid_list = [
    """
@external
def foo(x: uint256) -> bytes32:
    return convert(x, bytes32)
    """,
    """
@external
def foo(x: uint160) -> address:
    return convert(x, address)
    """,
    """
@external
def foo(x: address) -> uint256:
    return convert(x, uint256)
    """,
    """
flag Foo:
    A
    B

@external
def foo(x: Foo) -> uint256:
    return convert(x, uint256)
    """,
    """
@external
def foo(x: Bytes[32]) -> uint256:
    return convert(x, uint256)
    """,
    """
@external
def foo(x: Bytes[64]) -> Bytes[32]:
    return convert(x, Bytes[32])
    """,
]


@pytest.mark.parametrize("code", valid_list)
def test_convert_pass(code):
    assert compile_code(code) is not None
