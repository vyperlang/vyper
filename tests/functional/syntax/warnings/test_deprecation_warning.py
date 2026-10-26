import json
import warnings

import pytest

import vyper
from vyper.cli.vyper_json import compile_json
from vyper.exceptions import ImmutableViolation

deprecated = [
    """
struct Foo:
    a: uint256
    b: uint256

@external
def foo():
    f: Foo = Foo({a: 128, b: 256})
    """,
    """
event Foo:
    a: uint256
    b: uint256

@external
def foo():
    log Foo({a: 128, b: 256})
    """,
    """
imm: immutable(uint256)

@deploy
def __init__(x: uint256):
    self.imm = x

@external
def report() -> uint256:
    return imm
    """,
    """
imm: immutable(uint256)

@deploy
def __init__(x: uint256):
    imm = x
    """,
]


@pytest.mark.parametrize("code", deprecated)
def test_deprecated_warning(code):
    with pytest.warns(vyper.warnings.Deprecation):
        vyper.compile_code(code)


def test_multiple_warnings():
    code = """
@external
def foo():
    selfdestruct(msg.sender)

@external
def bar():
    selfdestruct(tx.origin)
    """
    with warnings.catch_warnings(record=True) as ws:
        vyper.compile_code(code)

    assert len(ws) == 2
    for w in ws:
        msg = w.message.message
        assert "selfdestruct" in msg and "deprecated" in msg


def test_multiple_immutable_bare_access_warnings():
    code = """
imm: immutable(uint256)

@deploy
def __init__(x: uint256, y: uint256):
    imm = x
    imm = y
    """
    with warnings.catch_warnings(record=True) as ws:
        with pytest.raises(ImmutableViolation):
            vyper.compile_code(code)

    assert len(ws) == 2
    for w in ws:
        assert isinstance(w.message, vyper.warnings.Deprecation)
        assert w.message.message == "immutables should now be accessed through `self`"
        assert w.message.hint == "use `self.imm` instead"


def test_deprecated_optimize_boolean_flag():
    code = """
@external
def foo():
    pass
    """

    input_json = {
        "language": "Vyper",
        "sources": {"contracts/foo.vy": {"content": code}},
        "settings": {"outputSelection": {"*": ["*"]}, "optimize": True},
    }

    with pytest.warns(vyper.warnings.Deprecation):
        compile_json(json.dumps(input_json))
