from vyper.codegen.ir_basicblock import (
    TERMINAL_IR_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IROperant,
    IRLiteral,
)
from vyper.codegen.ir_function import IRFunction
from vyper.ir.compile_ir import PUSH, optimize_assembly

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
    "lg",
    "lt",
    "slt",
    "sgt",
]

OPERANT_ORDER_IRELEVANT_INSTRUCTIONS = [
    "xor",
    "or",
    "add",
    "mul",
    "eq",
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

NOT_IN_STACK = 1


def stack_map_get_depth_in(stack_map: list[str], op: IROperant) -> int:
    """
    Returns the depth of the first matching operand in the stack map.
    If the operand is not in the stack map, returns NOT_IN_STACK.
    """
    for i, stack_op in enumerate(stack_map[::-1]):
        if isinstance(stack_op, IROperant) and stack_op.value == op.value:
            return -i

    return NOT_IN_STACK


def stack_map_peek(stack_map: list[str], depth: int) -> IROperant:
    """
    Returns the top of the stack map.
    """
    return stack_map[-depth - 1]


def stack_map_poke(stack_map: list[str], depth: int, op: IROperant) -> None:
    """
    Pokes an operand at the given depth in the stack map.
    """
    stack_map[-depth - 1] = op


def stack_map_dup(stack_map: list[str], depth: int) -> None:
    stack_map.append(stack_map_peek(stack_map, depth))


def stack_map_swap(stack_map: list[str], depth: int) -> None:
    stack_map[-depth - 1], stack_map[-1] = stack_map[-1], stack_map[-depth - 1]


def stack_map_pop(stack_map: list[str]) -> None:
    stack_map.pop()


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
                op.use_count += 1
                dfg_inputs[op] = inst

            for op in res:
                dfg_outputs[op] = inst


visited_instructions = set()


def generate_evm(ctx: IRFunction) -> list[str]:
    assembly = []
    stack_map = []
    convert_ir_to_dfg(ctx)

    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            if inst.opcode != "select":
                continue

            ret_op = inst.get_output_operands()[0]

            block_a = ctx.get_basic_block(inst.operands[0].value)
            block_b = ctx.get_basic_block(inst.operands[2].value)

            block_a.phi_vars[ret_op] = (inst.operands[1], inst.operands[3])
            block_b.phi_vars[ret_op] = (inst.operands[3], inst.operands[1])

    for i, bb in enumerate(ctx.basic_blocks):
        if i != 0:
            assembly.append(f"_sym_label_{bb.label}")
            assembly.append("JUMPDEST")
        for inst in bb.instructions:
            _generate_evm_for_instruction_r(ctx, assembly, inst, stack_map)

    optimize_assembly(assembly)

    return assembly


def _generate_evm_for_instruction_r(
    ctx: IRFunction, assembly: list, inst: IRInstruction, stack_map: list[str]
) -> None:
    for op in inst.get_output_operands():
        target = dfg_inputs[op]
        if target.parent != inst.parent:
            continue
        _generate_evm_for_instruction_r(ctx, assembly, target, stack_map)

    if inst in visited_instructions:
        return
    visited_instructions.add(inst)

    # generate EVM for op
    opcode = inst.opcode
    operands = inst.get_input_operands()

    if opcode == "select":
        ret = inst.get_output_operands()[0]
        inputs = inst.get_input_variables()
        for input in inputs:
            input.value = ret.value
        return

    _emit_input_operands(ctx, assembly, operands, stack_map)

    for op in operands:
        # final_stack_depth = -(len(operands) - i - 1)
        ucc = inst.get_use_count_correction(op)
        assert op.use_count >= ucc, "Operand used up"
        depth = stack_map_get_depth_in(stack_map, op)
        assert depth != NOT_IN_STACK, "Operand not in stack"
        needs_copy = op.use_count - ucc > 1
        if needs_copy:
            assembly.append(f"DUP{-depth+1}")
            stack_map_dup(stack_map, -depth)
            op.use_count -= 1

    copy_count = 0
    i = 0
    for i in range(len(operands)):
        op = operands[i]
        final_stack_depth = -(len(operands) - i - 1)
        depth = stack_map_get_depth_in(stack_map, op)
        assert depth != NOT_IN_STACK, "Operand not in stack"
        in_place_op = stack_map_peek(stack_map, -final_stack_depth)
        is_in_place = in_place_op.value == op.value
        # is_in_place = depth == final_stack_depth

        if not is_in_place:
            if final_stack_depth == 0 and depth != 0:
                assembly.append(f"SWAP{-depth}")
                stack_map_swap(stack_map, -depth)
            elif final_stack_depth != 0 and depth == 0:
                assembly.append(f"SWAP{-final_stack_depth}")
                stack_map_swap(stack_map, -final_stack_depth)
            else:
                assembly.append(f"SWAP{-depth}")
                stack_map_swap(stack_map, -depth)
                assembly.append(f"SWAP{-final_stack_depth}")
                stack_map_swap(stack_map, -final_stack_depth)

    del stack_map[len(stack_map) - len(operands) :]
    if inst.ret is not None:
        stack_map.append(inst.ret)

    if opcode in ONE_TO_ONE_INSTRUCTIONS:
        assembly.append(opcode.upper())
    elif opcode == "jnz":
        assembly.append(f"_sym_label_{inst.operands[1].value}")
        assembly.append("JUMPI")
    elif opcode == "jmp":
        assembly.append(f"_sym_label_{inst.operands[0].value}")
        assembly.append("JUMP")
    elif opcode == "gt":
        assembly.append("GT")
    elif opcode == "lt":
        assembly.append("LT")
    elif opcode == "ret":
        assembly.append("RETURN")
    elif opcode == "select":
        pass
    else:
        raise Exception(f"Unknown opcode: {opcode}")

    for i in range(copy_count):
        assembly.append("SWAP1")
        assembly.append("POP")


def _emit_input_operands(
    ctx: IRFunction, assembly: list, ops: list[IROperant], stack_map: list[str]
) -> None:
    for op in ops:
        if op.is_literal:
            assembly.extend([*PUSH(op.value)])
            stack_map.append(op)
            continue
        _generate_evm_for_instruction_r(ctx, assembly, dfg_outputs[op], stack_map)
