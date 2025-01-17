import contextlib
import decimal
import os

from vyper import ast as vy_ast
from vyper.compiler.phases import CompilerData
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


def check_precompile_asserts(source_code):
    # check deploy IR (which contains runtime IR)
    ir_node = CompilerData(source_code).ir_nodes

    def _check(ir_node, parent=None):
        if ir_node.value == "staticcall":
            precompile_addr = ir_node.args[1]
            if isinstance(precompile_addr.value, int) and precompile_addr.value < 10:
                assert parent is not None and parent.value == "assert"
        for arg in ir_node.args:
            _check(arg, ir_node)

    _check(ir_node)
