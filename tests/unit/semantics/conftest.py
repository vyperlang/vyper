import pytest

from vyper import ast as vy_ast


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
def fresh_namespace():
    """
    Yields a clean `Namespace` object.
    """
    from vyper.semantics.namespace import Namespace

    with Namespace.new_scope():
        yield
