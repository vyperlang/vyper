from vyper.codegen.ir_basicblock import TERMINAL_IR_INSTRUCTIONS, IRBasicBlock, IRInstruction, IROperant
from vyper.codegen.ir_function import IRFunction

ONE_TO_ONE_INSTRUCTIONS = [
    "revert",
    "assert",
    "calldatasize", 
    "calldatacopy", 
    "calldataload", 
    "callvalue", 
    "shr",
    "xor",
    "or",
    "add",
    "sub",
    "mul",
    "div",
    "eq",
    "iszero",
]

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
    global dfg_inputs
    global dfg_outputs
    dfg_inputs = {}
    dfg_outputs = {}
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            operands = inst.get_input_variables()
            res = inst.get_output_operands()

            for op in operands:
                dfg_inputs[op] = inst

            for op in res:
                dfg_outputs[op] = inst

def convert_bb_to_dfg(ctx: IRFunction, bb: IRBasicBlock) -> None:
    global dfg_inputs
    global dfg_outputs
    dfg_inputs = {}
    dfg_outputs = {}
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
    assembly = []

    FIXED = set(["ret", "assert", "revert"])

    #convert_ir_to_dfg(ctx)

    for i, bb in enumerate(ctx.basic_blocks):
        convert_bb_to_dfg(ctx,bb)
        if i != 0:
            assembly.append(f"_label_{bb.label}")
            assembly.append("JUMPDEST")
        for inst in bb.instructions:
            _generate_evm_for_instruction_r(ctx, assembly, inst, FIXED)
        for inst in bb.instructions:
            _generate_evm_for_instruction_r(ctx, assembly, inst)

    return assembly

def _generate_evm_for_instruction_r(ctx: IRFunction, assembly: list, inst: IRInstruction, fixed: set = set()) -> None:
    # Basically handle fences unmovable instructions etc WIP
    if inst.opcode in fixed:
        return
    
    for op in inst.get_output_operands():
       _generate_evm_for_instruction_r(ctx, assembly, dfg_inputs[op], fixed)

    if inst in visited_instructions:
        return
    visited_instructions.add(inst)

    operands = inst.get_input_operands()

    # generate EVM for op
    opcode = inst.opcode

    # if opcode in ["le"]:
    #     operands.reverse()

    _emit_input_operands(ctx, assembly, operands, fixed)
    #print("Generating EVM for", inst)
    if opcode in ONE_TO_ONE_INSTRUCTIONS:
        assembly.append(opcode.upper())
    elif opcode == "jnz":
        assembly.append(f"_label_{inst.operands[1].value}")
        assembly.append("JUMPI")
    elif opcode == "jmp":
        assembly.append(f"_label_{inst.operands[0].value}")
        assembly.append("JUMP")
    elif opcode == "le":
        assembly.append("GT")
    elif opcode == "ge":
        assembly.append("LT")
    elif opcode == "ret":
        assembly.append("RETURN")
    elif opcode == "select":
        assembly.append("select") # TODO: Implement
    else:
        raise Exception(f"Unknown opcode: {opcode}")


def _emit_input_operands(ctx: IRFunction, assembly: list, ops: list[IROperant], fixed: set) -> None:
    for op in ops:
        if isinstance(op, int):
            assembly.append(f"PUSH1")
            assembly.append(f"{op:#x}")
            continue
        _generate_evm_for_instruction_r(ctx, assembly, dfg_outputs[op], fixed)
    
