from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_ir


def test_simple(get_contract_from_ir):
    ir = ["calldatacopy", 32, 0, ["calldatasize"]]
    ir = IRnode.from_list(ir)
    print(ir)
    deploy, runtime = generate_ir(ir, OptimizationLevel.NONE)
    assert deploy is None
    assert runtime is not None
    assert len(runtime.basic_blocks) == 1
    bb = runtime.basic_blocks[0]
    assert len(bb.instructions) == 3

    correct_venom = """IRFunction: __global
__global:  IN=[] OUT=[] => {} 
    %1 = calldatasize 
    calldatacopy %1, 0, 32
    stop"""

    assert str(runtime) == correct_venom
