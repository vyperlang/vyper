from vyper.exceptions import FunctionDeclarationException


def test_invalid_if_both_public_and_internal(assert_compile_failed, get_contract):
    code = """
@external
@internal
def foo():
    x: uint256 = 1
"""

    assert_compile_failed(lambda: get_contract(code), FunctionDeclarationException)


def test_invalid_if_visibility_isnt_declared(assert_compile_failed, get_contract):
    code = """
def foo():
    x: uint256 = 1
"""

    assert_compile_failed(lambda: get_contract(code), FunctionDeclarationException)
