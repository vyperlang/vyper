from vyper.codegen.ir_basicblock import TERMINAL_IR_INSTRUCTIONS, IRInstruction, IROperant
from vyper.codegen.ir_function import IRFunction


class DFGNode:
    value: IRInstruction | IROperant
    predecessors: list["DFGNode"]
    successors: list["DFGNode"]

    def __init__(self, value: IRInstruction | IROperant):
        self.value = value
        self.predecessors = []
        self.successors = []


dfg_inputs = {}
dfg_outputs = {}


def convert_ir_to_dfg(ctx: IRFunction) -> None:
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            operands = inst.get_input_variables()
            res = inst.get_output_operands()

            for op in operands:
                dfg_inputs[op] = inst

            for op in res:
                dfg_outputs[op] = inst


visited_instructions = set()


def generate_evm(ctx: IRFunction) -> list[str]:
    dfg_inputs = {}
    dfg_outputs = {}

    assembly = []

    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            _generate_evm_for_instruction_r(assembly, inst)

    return assembly


def _generate_evm_for_instruction_r(assembly: list, inst: IRInstruction) -> None:
    if inst in visited_instructions:
        return

    visited_instructions.add(inst)

    for op in inst.get_input_operands():
        _generate_evm_for_instruction_r(assembly, dfg_outputs[op])

    # Basically handle fences unmovable instructions etc WIP
    # if inst.opcode in ["ret"]:
    #     return
    # generate EVM for op
    print("Generating EVM for instruction: ", inst)
    _generate_evm_for_instruction(assembly, inst)

    # for op in inst.get_output_operands():
    #    _generate_evm_for_instruction_r(assembly, dfg_inputs[op])


def _generate_evm_for_instruction(assembly: list, inst: IRInstruction) -> None:
    opcode = inst.opcode

    if opcode == "calldatasize":
        assembly.append("CALLDATASIZE")
    elif opcode == "calldatacopy":
        assembly.append("CALLDATACOPY")
    elif opcode == "le":
        assembly.append("LE")
