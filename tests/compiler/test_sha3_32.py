from vyper.codegen.ir_node import IRnode
from vyper.ir import compile_ir, optimizer


def test_sha3_32():
    ir = ["sha3_32", 0]
    evm = ["PUSH1", 0, "PUSH1", 0, "MSTORE", "PUSH1", 32, "PUSH1", 0, "SHA3"]
    assert compile_ir.compile_to_assembly(IRnode.from_list(ir)) == evm
    assert compile_ir.compile_to_assembly(optimizer.optimize(IRnode.from_list(ir))) == evm
