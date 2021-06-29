import pytest

from vyper import ast as vy_ast
from vyper.semantics.namespace import get_namespace


@pytest.fixture(scope="session")
def build_node():
    """
    Yields a helper function for generating a single Vyper AST node.
    """

    def _build_node(source):
        # docstring ensures string nodes are properly generated, not turned into docstrings
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
    obj = get_namespace()
    obj.clear()
    yield obj
    obj.clear()
