import pytest

from vyper import ast as vy_ast
from vyper.context import namespace as ns


@pytest.fixture(scope="session")
def build_node():
    """
    Yields a helper function for generating a single Vyper AST node.
    """

    def _build_node(source):
        source = f"""'I am a docstring.'\n{source}"""
        ast = vy_ast.parse_to_ast(source).body[0]
        if isinstance(ast, vy_ast.Expr):
            ast = ast.value
        return ast

    yield _build_node


@pytest.fixture
def namespace():
    """
    Yields a clean `Namespace` object.
    """
    obj = ns.get_namespace()
    obj.clear()
    yield obj
    obj.clear()
