from vyper.ast_utils import (
    ast_to_string,
    parse_to_ast,
)


def test_ast_to_string():
    code = """
@public
def testme(a: int128) -> int128:
    return a
    """
    vyper_ast = parse_to_ast(code)
    assert ast_to_string(vyper_ast) == (
        "Module(body=[FunctionDef(name='testme', args=arguments(args=[arg(arg='a',"
        " annotation=Name(id='int128'))], defaults=[]), body=[Return(value=Name(id='a'))],"
        " decorator_list=[Name(id='public')], returns=Name(id='int128'))])"
    )
