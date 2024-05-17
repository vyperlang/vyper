import contextlib
import decimal
import os

from vyper import ast as vy_ast
from vyper.semantics.analysis.constant_folding import constant_fold
from vyper.utils import DECIMAL_EPSILON, round_towards_zero

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


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


def decimal_to_int(*args):
    s = decimal.Decimal(*args)
    return round_towards_zero(s / DECIMAL_EPSILON)
