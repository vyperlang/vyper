import contextlib
import os

from vyper import ast as vy_ast
from vyper.semantics.analysis.constant_folding import constant_fold


@contextlib.contextmanager
def working_directory(directory):
    tmp = os.getcwd()
    try:
        os.chdir(directory)
        yield
    finally:
        os.chdir(tmp)


def parse_and_fold(source_code):
    ast = vy_ast.parse_to_ast(source_code)
    constant_fold(ast)
    return ast
