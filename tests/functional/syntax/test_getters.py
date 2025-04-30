import pytest

from vyper.compiler import compile_code
from vyper.exceptions import SyntaxException


def test_duplicate_public_annotation():
    code = """
a: public(public(uint256))
    """

    with pytest.raises(SyntaxException) as e:
        compile_code(code)

    assert e.value.message == "Used variable annotation `public` multiple times"


def test_duplicate_reentrant_annotation():
    code = """
a: reentrant(reentrant(uint256))
    """

    with pytest.raises(SyntaxException) as e:
        compile_code(code)

    assert e.value.message == "Used variable annotation `reentrant` multiple times"
