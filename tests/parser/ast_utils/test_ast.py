from vyper.ast_utils import (
    parse_to_ast,
)


def test_ast_equal():
    code = """
@public
def test() -> int128:
    a: uint256 = 100
    return 123
    """

    ast1 = parse_to_ast(code)
    ast2 = parse_to_ast("\n   \n" + code + "\n\n")

    assert ast1 == ast2


def test_ast_unequal():
    code1 = """
@public
def test() -> int128:
    a: uint256 = 100
    return 123
    """
    code2 = """
@public
def test() -> int128:
    a: uint256 = 100
    return 121
    """

    ast1 = parse_to_ast(code1)
    ast2 = parse_to_ast(code2)

    assert ast1 != ast2
