import json

import pytest

import vyper
from vyper.cli.vyper_json import compile_json

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
]


@pytest.mark.parametrize("code", deprecated)
def test_deprecated_warning(code):
    with pytest.warns(vyper.warnings.Deprecation):
        vyper.compile_code(code)


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
