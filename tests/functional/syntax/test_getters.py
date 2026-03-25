import pytest

from vyper.compiler import compile_code
from vyper.exceptions import SyntaxException


@pytest.mark.parametrize("annotation", ("public", "reentrant"))
def test_duplicate_getter_annotation(annotation):
    code = f"""
a: {annotation}({annotation}(uint256))
    """

    with pytest.raises(SyntaxException) as e:
        compile_code(code)

    assert e.value.message == f"Used variable annotation `{annotation}` multiple times"


@pytest.mark.parametrize("annotation", ("constant", "transient", "immutable"))
def test_duplicate_location_annotation(annotation):
    code = f"""
a: {annotation}({annotation}(uint256))
    """

    with pytest.raises(SyntaxException) as e:
        compile_code(code)

    # TODO: improve this error message
    assert e.value.message == "Invalid scope for variable declaration"
