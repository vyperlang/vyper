import pytest

from vyper import compiler
from vyper.exceptions import InvalidReference

fail_list = [
    """
x: uint256

@external
def foo():
    send(0x1234567890123456789012345678901234567890, x)
    """,
    """
@external
def bar(x: int128) -> int128:
    return 3 * x

@external
def foo() -> int128:
    return bar(20)
    """,
    """
b: int128
@external
def foo():
    b = 7
    """,
    """
x: int128
@external
def foo():
    x = 5
    """,
    """
@external
def foo():
    int128 = 5
    """,
    """
a: public(constant(uint256)) = 1

@external
def foo():
    b: uint256 = self.a
    """,
    # parameterized types live in the namespace as the type class rather than an
    # instance, so they used to miss the TYPE_T check and panic on `t.typ`
    # instead of reporting a bad reference
    # see https://github.com/vyperlang/vyper/issues/3246
    """
@external
def foo():
    x: uint256 = Bytes[32]
    """,
    """
@external
def foo():
    x: uint256 = String[10]
    """,
    """
@external
def foo():
    x: uint256 = DynArray[uint256, 3]
    """,
    """
@external
def foo():
    x: uint256 = HashMap[uint256, uint256]
    """,
    """
@external
def foo() -> uint256:
    return Bytes[32]
    """,
    """
@external
def foo() -> Bytes[64]:
    return abi_encode(Bytes[32])
    """,
    # module scope reaches the same guard through constant folding rather than
    # function body analysis
    # see https://github.com/vyperlang/vyper/issues/4434
    """
MAX: constant(uint256) = DynArray[uint256, 10]
    """,
    # an unsubscripted name arrives at types_from_Name directly instead of
    # through types_from_Subscript
    """
@external
def foo():
    x: uint256 = DynArray
    """,
    # as the index of another subscript
    # see https://github.com/vyperlang/vyper/issues/4733
    """
@external
def foo(a: uint256[3]) -> uint256:
    return a[Bytes[32]]
    """,
    # attribute access is the one route that asks for types with
    # include_type_exprs enabled
    """
@external
def foo():
    x: uint256 = DynArray.foo
    """,
    # module level statements resolve names without entering a function body
    """
initializes: HashMap
    """,
    """
uses: String
    """,
    """
exports: DynArray
    """,
    # a default argument is analyzed with the signature, not the body
    """
@external
def foo(a: uint256 = Bytes[32]):
    pass
    """,
    # keyword arguments take their own validation route
    """
struct S:
    a: uint256

@external
def foo():
    s: S = S(a=Bytes[32])
    """,
    """
event E:
    a: uint256

@external
def foo():
    log E(a=Bytes[32])
    """,
    # a vararg builtin other than abi_encode, to show the guard is not specific
    # to one builtin's argument handling
    """
@external
def foo() -> Bytes[64]:
    return concat(b"a", Bytes[32])
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_invalid_reference_exception(bad_code):
    with pytest.raises(InvalidReference):
        compiler.compile_code(bad_code)


def test_parameterized_type_message():
    # the guard reuses the wording concrete type names already get, so a
    # regression that routed one of these through a different path would
    # still raise InvalidReference but with different text
    code = """
@external
def foo():
    x: uint256 = DynArray[uint256, 3]
    """
    with pytest.raises(InvalidReference, match="not a variable or literal: 'DynArray'"):
        compiler.compile_code(code)
