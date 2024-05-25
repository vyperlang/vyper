import pytest

from vyper import compile_code
from vyper.exceptions import VyperException

fail_list = [
    # VALUE is not set in the constructor
    """
VALUE: immutable(uint256)

@deploy
def __init__():
    pass
    """,
    # no `__init__` function, VALUE not set
    """
VALUE: immutable(uint256)

@view
@external
def get_value() -> uint256:
    return VALUE
    """,
    # VALUE given an initial value
    """
VALUE: immutable(uint256) = 3

@deploy
def __init__():
    pass
    """,
    # setting value outside of constructor
    """
VALUE: immutable(uint256)

@deploy
def __init__():
    VALUE = 0

@external
def set_value(_value: uint256):
    VALUE = _value
    """,
    # modifying immutable multiple times in constructor
    """
VALUE: immutable(uint256)

@deploy
def __init__(_value: uint256):
    VALUE = _value * 3
    VALUE = VALUE + 1
    """,
    # immutable(public()) banned
    """
VALUE: immutable(public(uint256))

@deploy
def __init__(_value: uint256):
    VALUE = _value * 3
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_compilation_fails_with_exception(bad_code):
    with pytest.raises(VyperException):
        compile_code(bad_code)


types_list = (
    "uint256",
    "int256",
    "int128",
    "address",
    "bytes32",
    "decimal",
    "bool",
    "Bytes[64]",
    "String[10]",
)


@pytest.mark.parametrize("typ", types_list)
def test_compilation_simple_usage(typ):
    code = f"""
VALUE: immutable({typ})

@deploy
def __init__(_value: {typ}):
    VALUE = _value

@view
@external
def get_value() -> {typ}:
    return VALUE
    """

    assert compile_code(code)


pass_list = [
    # using immutable allowed in constructor
    """
VALUE: immutable(uint256)

@deploy
def __init__(_value: uint256):
    VALUE = _value * 3
    x: uint256 = VALUE + 1
    """
]


@pytest.mark.parametrize("good_code", pass_list)
def test_compilation_success(good_code):
    assert compile_code(good_code)


fail_list_with_messages = [
    (
        """
imm: immutable(uint256)

@deploy
def __init__(x: uint256):
    self.imm = x
    """,
        "Immutable variables must be accessed without 'self'",
    ),
    (
        """
imm: immutable(uint256)

@deploy
def __init__(x: uint256):
    x = imm

@external
def report():
    y: uint256 = imm + imm
    """,
        "Immutable definition requires an assignment in the constructor",
    ),
    (
        """
imm: immutable(uint256)

@deploy
def __init__(x: uint256):
    imm = x

@external
def report():
    y: uint256 = imm
    z: uint256 = self.imm
    """,
        "'imm' is not a storage variable, it should not be prepended with self",
    ),
    (
        """
struct Foo:
    a : uint256

x: immutable(Foo)

@deploy
def __init__():
    x = Foo(a=1)

@external
def hello() :
    x.a =  2
    """,
        "Immutable value cannot be written to",
    ),
]


@pytest.mark.parametrize(["bad_code", "message"], fail_list_with_messages)
def test_compilation_fails_with_exception_message(bad_code: str, message: str):
    with pytest.raises(VyperException) as excinfo:
        compile_code(bad_code)
    assert excinfo.value.message == message
