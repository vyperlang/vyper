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
    # common sanity check for some tests, that calls to precompiles
    # are correctly wrapped in an assert.

    compiler_data = CompilerData(source_code)
    deploy_ir = compiler_data.ir_nodes
    runtime_ir = compiler_data.ir_runtime

    def _check(ir_node, parent=None):
        if ir_node.value == "staticcall":
            precompile_addr = ir_node.args[1]
            if isinstance(precompile_addr.value, int) and precompile_addr.value < 10:
                assert parent is not None and parent.value == "assert"
        for arg in ir_node.args:
            _check(arg, ir_node)

    _check(deploy_ir)
    # technically runtime_ir is contained in deploy_ir, but check it anyways.
    _check(runtime_ir)
