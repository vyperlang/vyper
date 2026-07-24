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


def test_json_abi_error_preserves_unnamed_inputs():
    err = ErrorT.from_abi(
        {
            "type": "error",
            "name": "Foo",
            "inputs": [{"name": "", "type": "uint256"}, {"name": "", "type": "uint256"}],
        }
    )

    assert list(err.arguments) == ["_arg0", "_arg1"]
    assert err.signature == "Foo(uint256,uint256)"
    assert err.selector == method_id_int("Foo(uint256,uint256)")


def test_json_abi_error_preserves_duplicate_inputs():
    err = ErrorT.from_abi(
        {
            "type": "error",
            "name": "Foo",
            "inputs": [{"name": "value", "type": "uint256"}, {"name": "value", "type": "address"}],
        }
    )

    assert list(err.arguments) == ["value", "_arg1"]
    assert err.signature == "Foo(uint256,address)"
