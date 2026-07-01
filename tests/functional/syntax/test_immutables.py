import pytest

from vyper import compile_code
from vyper.exceptions import ImmutableViolation, VyperException

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
    return self.VALUE
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
    self.VALUE = 0

@external
def set_value(_value: uint256):
    self.VALUE = _value
    """,
    # modifying immutable multiple times in constructor
    """
VALUE: immutable(uint256)

@deploy
def __init__(_value: uint256):
    self.VALUE = _value * 3
    self.VALUE = self.VALUE + 1
    """,
    # immutable(public()) banned
    """
VALUE: immutable(public(uint256))

@deploy
def __init__(_value: uint256):
    self.VALUE = _value * 3
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_compilation_fails_with_exception(bad_code):
    with pytest.raises(VyperException):
        compile_code(bad_code)


def test_augassign_modification():
    code = """
VALUE: immutable(uint256)

@deploy
def __init__():
    self.VALUE = 1
    self.VALUE += 1
    """
    with pytest.raises(ImmutableViolation) as e:
        compile_code(code)
    assert e.value.message == "Immutable value cannot be modified after assignment"


def test_augassign_setting():
    code = """
VALUE: immutable(uint256)

@deploy
def __init__():
    self.VALUE += 1
    """
    with pytest.raises(ImmutableViolation) as e:
        compile_code(code)
    assert e.value.message == "Immutable definition requires an assignment in the constructor"


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
    self.VALUE = _value

@view
@external
def get_value() -> {typ}:
    return self.VALUE
    """

    assert compile_code(code)


pass_list = [
    # using immutable allowed in constructor
    """
VALUE: immutable(uint256)

@deploy
def __init__(_value: uint256):
    self.VALUE = _value * 3
    x: uint256 = self.VALUE + 1
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

@external
def report() -> uint256:
    return imm
    """,
        "'imm'",
        "did you mean self.imm?",
    ),
    (
        """
imm: immutable(uint256)

@deploy
def __init__(x: uint256):
    imm = x
    """,
        # TODO: not great UX, the user did try to assign, we should point them to how to fix it
        "Immutable definition requires an assignment in the constructor",
        None,
    ),
    (
        """
struct Foo:
    a : uint256

x: immutable(Foo)

@deploy
def __init__():
    self.x = Foo(a=1)

@external
def hello() :
    self.x.a =  2
    """,
        "Immutable value cannot be written to",
        None,
    ),
    (
        """
VALUE: immutable(uint256)

@deploy
def __init__():
    self.VALUE = 1

@external
def bump():
    self.VALUE += 1
    """,
        "Immutable value cannot be written to",
        None,
    ),
]


@pytest.mark.parametrize(["bad_code", "message", "hint"], fail_list_with_messages)
def test_compilation_fails_with_exception_message(
    bad_code: str, message: str, hint: str | None
):
    with pytest.raises(VyperException) as excinfo:
        compile_code(bad_code)
    assert excinfo.value.message == message
    assert excinfo.value.hint == hint
