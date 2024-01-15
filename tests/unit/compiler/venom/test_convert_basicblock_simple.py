from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_ir


def test_simple():
    ir = ["calldatacopy", 32, 0, ["calldatasize"]]
    ir_node = IRnode.from_list(ir)
    deploy, runtime = generate_ir(ir_node, OptimizationLevel.NONE)
    assert deploy is None
    assert runtime is not None

    correct_venom = """IRFunction: __global
__global:  IN=[] OUT=[] => {}
    %1 = calldatasize
    calldatacopy %1, 0, 32
    stop"""

    assert str(runtime) == correct_venom
