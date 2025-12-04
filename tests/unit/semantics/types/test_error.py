import pytest

from vyper.semantics.types.user import ErrorT
from vyper.utils import method_id_int


ERROR_ID_TESTS = [
    ("error Unauthorized: pass", "Unauthorized()", method_id_int("Unauthorized()")),
    (
        """error InsufficientBalance:
    available: uint256
    required: uint256
""",
        "InsufficientBalance(uint256,uint256)",
        method_id_int("InsufficientBalance(uint256,uint256)"),
    ),
]


@pytest.mark.parametrize("source,signature,selector", ERROR_ID_TESTS)
def test_error_selector(build_node, source, signature, selector):
    node = build_node(source)
    err = ErrorT.from_ErrorDef(node)

    assert err.signature == signature
    assert err.selector == selector
