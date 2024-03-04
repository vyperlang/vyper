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
    ( # staticcall without assigning result disallowed
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
]


@pytest.mark.parametrize("code,exc_type,msg,hint", bad)
def test_bad(code, exc_type, msg, hint):
    with pytest.raises(exc_type) as e:
        _ = compile_code(code)
    assert e.value._message == msg
    assert e.value._hint == hint
