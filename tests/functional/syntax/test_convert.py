import itertools

import pytest

from vyper import compile_code
from vyper.builtins._convert_rules import validate_convertibility
from vyper.exceptions import InvalidType, StructureException, TypeMismatch
from vyper.semantics.types import AddressT, BoolT, BytesM_T, BytesT, DecimalT, IntegerT, StringT

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
    (  # oversize bytestring -> uint256
        """
@external
def foo(x: Bytes[33]) -> uint256:
    return convert(x, uint256)
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


def _type_instances():
    types = [BoolT(), AddressT(), DecimalT()]
    types += [IntegerT(is_signed, bits) for is_signed in (True, False) for bits in (8, 128, 256)]
    types += [BytesM_T(m) for m in (1, 20, 32)]
    types += [BytesT(32), BytesT(33), StringT(32), StringT(33)]
    return types


@pytest.mark.parametrize("in_typ,out_typ", itertools.product(_type_instances(), repeat=2))
def test_frontend_matches_shared_rules(in_typ, out_typ):
    # the frontend must reject exactly the pairs the shared conversion
    # matrix rejects (modulo the same-type check, which raises earlier)
    if in_typ.is_subtype_of(out_typ):
        return  # same-type conversions are blocked before the matrix check

    code = f"""
@external
def foo(x: {in_typ}) -> {out_typ}:
    return convert(x, {out_typ})
    """

    try:
        validate_convertibility(in_typ, out_typ)
        legal = True
    except (TypeMismatch, StructureException):
        legal = False

    if legal:
        assert compile_code(code, output_formats=ANALYSIS_ONLY) is not None
    else:
        with pytest.raises((TypeMismatch, StructureException)):
            compile_code(code, output_formats=ANALYSIS_ONLY)
