from vyper.codegen.ir_basicblock import IRInstruction
from vyper.codegen.ir_function import IRFunction, IRInstruction


class DFGNode:
    instruction: IRInstruction
    predecessors: list["DFGNode"]
    successors: list["DFGNode"]


def convert_ir_to_dfg(ir: IRFunction) -> DFGNode:
    dfg_nodes = {}

    for bb in ir.basic_blocks:
        for inst in bb.instructions:
            operands = inst.get_input_operands()
            res = inst.get_output_operands()[0]

            if res in dfg_nodes:
                result_node = dfg_nodes[res]
            else:
                result_node = DFGNode(res)
                dfg_nodes[res] = result_node
