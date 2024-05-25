import pytest

from vyper.compiler import compile_code
from vyper.exceptions import CallViolation, StructureException

good = [
    # payable and nonpayable, "plain" (no assignment)
    """
interface Foo:
    def foo(): payable
    def bar() -> uint256: nonpayable

@external
def foo(f: Foo):
    extcall f.foo()
    extcall f.bar()
    """,
    """
interface Foo:
    def foo(): nonpayable
    def bar() -> uint256: nonpayable

@external
def foo(f: Foo):
    extcall f.foo()
    extcall f.bar()
    """,
    # payable and nonpayable, with assignment
    """
interface Foo:
    def foo() -> uint256: payable

@external
def foo(f: Foo):
    s: uint256 = extcall f.foo()
    """,
    """
interface Foo:
    def foo() -> uint256: nonpayable

@external
def foo(f: Foo):
    s: uint256 = extcall f.foo()
    """,
    # view and pure functions
    """
interface Foo:
    def foo() -> uint256: view

@external
def foo(f: Foo):
    s: uint256 = staticcall f.foo()
    """,
    # view and pure functions
    """
interface Foo:
    def foo() -> uint256: pure

@external
def foo(f: Foo):
    s: uint256 = staticcall f.foo()
    """,
    # TODO: tokenizer currently has issue with log+staticcall/extcall, e.g.
    # `log Bar(staticcall f.foo() + extcall f.bar())`
]


@pytest.mark.parametrize("code", good)
def test_good(code):
    _ = compile_code(code)


bad = [
    (
        """
interface Foo:
    def foo() -> uint256: pure

@internal
def bar(f: Foo):
    f.foo()
    """,
        CallViolation,
        "Calls to external pure functions must use the `staticcall` keyword.",
        "try `staticcall f.foo()`",
    ),
    (
        """
interface Foo:
    def foo() -> uint256: view

@internal
def bar(f: Foo):
    f.foo()
    """,
        CallViolation,
        "Calls to external view functions must use the `staticcall` keyword.",
        "try `staticcall f.foo()`",
    ),
    (
        """
interface Foo:
    def foo() -> uint256: nonpayable

@internal
def bar(f: Foo):
    f.foo()
    """,
        CallViolation,
        "Calls to external nonpayable functions must use the `extcall` keyword.",
        "try `extcall f.foo()`",
    ),
    (
        """
interface Foo:
    def foo() -> uint256: payable

@internal
def bar(f: Foo):
    f.foo()
    """,
        CallViolation,
        "Calls to external payable functions must use the `extcall` keyword.",
        "try `extcall f.foo()`",
    ),
    (
        """
interface Foo:
    def foo() -> uint256: nonpayable

@internal
def bar(f: Foo):
    s: uint256 = staticcall f.foo()
    """,
        CallViolation,
        "Calls to external nonpayable functions must use the `extcall` keyword.",
        "try `extcall f.foo()`",
    ),
    (
        """
interface Foo:
    def foo() -> uint256: view

@internal
def bar(f: Foo):
    s: uint256 = extcall f.foo()
    """,
        CallViolation,
        "Calls to external view functions must use the `staticcall` keyword.",
        "try `staticcall f.foo()`",
    ),
    (  # staticcall without assigning result disallowed
        """
interface Foo:
    def foo() -> uint256: view

@internal
def bar(f: Foo):
    staticcall f.foo()
    """,
        StructureException,
        "Expressions without assignment are disallowed",
        "did you mean to assign the result to a variable?",
    ),
    (
        """
interface Foo:
    def foo() -> uint256: view

@internal
def bar(f: Foo):
    staticcall f.foo()
    """,
        StructureException,
        "Expressions without assignment are disallowed",
        "did you mean to assign the result to a variable?",
    ),
    (
        """
@internal
def foo() -> uint256:
    return 1

@internal
def bar():
    s: uint256 = staticcall self.foo()
    """,
        CallViolation,
        "Calls to internal functions cannot use the `staticcall` keyword.",
        "remove the `staticcall` keyword",
    ),
    (
        """
@internal
def foo() -> uint256:
    return 1

@internal
def bar():
    s: uint256 = extcall self.foo()
    """,
        CallViolation,
        "Calls to internal functions cannot use the `extcall` keyword.",
        "remove the `extcall` keyword",
    ),
    (
        """
@internal
def foo():
    pass

@internal
def bar():
    extcall self.foo()
    """,
        CallViolation,
        "Calls to internal functions cannot use the `extcall` keyword.",
        "remove the `extcall` keyword",
    ),
    (
        """
@internal
def bar():
    extcall x
    """,
        StructureException,
        "`extcall` must be followed by a function call",
        "did you forget parentheses?",
    ),
    (
        """
@internal
def bar():
    staticcall x
    """,
        StructureException,
        "`staticcall` must be followed by a function call",
        "did you forget parentheses?",
    ),
    (  # test cannot call builtin
        """
@internal
def bar():
    extcall raw_call(msg.sender, b"")
    """,
        CallViolation,
        "cannot use `extcall` here!",
        "remove the `extcall` keyword",
    ),
    (  # test cannot call MemberFunctionT
        """
@internal
def bar():
    s: DynArray[uint256, 6] = []
    extcall s.pop()
    """,
        CallViolation,
        "cannot use `extcall` here!",
        "remove the `extcall` keyword",
    ),
    (  # test cannot extcall struct ctor
        """
struct Foo:
    x: uint256
@internal
def bar():
    s: Foo = extcall Foo(x=1)
    """,
        CallViolation,
        "cannot use `extcall` here!",
        "remove the `extcall` keyword",
    ),
    # maybe this test belongs in the logging tests
    (  # test cannot extcall log ctor
        """
event Foo:
    x: uint256
@internal
def bar():
    log extcall Foo(1)
    """,
        StructureException,
        "Log must call an event",
        None,
    ),
    (  # test cannot extcall event ctor
        """
event Foo:
    x: uint256
@internal
def bar():
    extcall Foo(1)
    """,
        StructureException,
        "To call an event you must use the `log` statement",
        None,
    ),
    (  # test cannot extcall interface ctor
        """
interface Foo:
    def foo(): nonpayable

@internal
def bar():
    extcall Foo(msg.sender)
    """,
        StructureException,
        "Function `type(interface Foo)` cannot be called without assigning the result",
        None,
    ),
]


@pytest.mark.parametrize("code,exc_type,msg,hint", bad)
def test_bad(code, exc_type, msg, hint):
    with pytest.raises(exc_type) as e:
        _ = compile_code(code)
    assert e.value._message == msg
    assert e.value._hint == hint
