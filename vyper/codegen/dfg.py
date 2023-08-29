from vyper.codegen.ir_basicblock import IRInstruction, IRLabel, IROperand, IRVariable
from vyper.codegen.ir_function import IRFunction
from vyper.compiler.utils import StackMap
from vyper.ir.compile_ir import PUSH, RuntimeHeader, optimize_assembly
from vyper.utils import MemoryPositions

ONE_TO_ONE_INSTRUCTIONS = [
    "revert",
    "calldatasize",
    "calldatacopy",
    "calldataload",
    "gas",
    "returndatasize",
    "returndatacopy",
    "callvalue",
    "selfbalance",
    "sload",
    "sstore",
    "timestamp",
    "caller",
    "shr",
    "shl",
    "and",
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
    "log0",
    "log1",
    "log2",
    "log3",
    "log4",
]

OPERAND_ORDER_IRELEVANT_INSTRUCTIONS = ["xor", "or", "add", "mul", "eq"]


class DFGNode:
    value: IRInstruction | IROperand
    predecessors: list["DFGNode"]
    successors: list["DFGNode"]

    def __init__(self, value: IRInstruction | IROperand):
        self.value = value
        self.predecessors = []
        self.successors = []


dfg_inputs = {str: [IRInstruction]}
dfg_outputs = {str: IRInstruction}


def convert_ir_to_dfg(ctx: IRFunction) -> None:
    global dfg_inputs
    global dfg_outputs
    dfg_inputs = {}
    dfg_outputs = {}
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            variables = inst.get_input_variables()
            res = inst.get_output_operands()

            for v in variables:
                v.use_count += 1
                dfg_inputs[v.value] = (
                    [inst] if dfg_inputs.get(v.value) is None else dfg_inputs[v.value] + [inst]
                )

            for op in res:
                dfg_outputs[op.value] = inst


visited_instructions = {IRInstruction}


def generate_evm(ctx: IRFunction, no_optimize: bool = False) -> list[str]:
    stack_map = StackMap()
    assembly = []
    asm = assembly

    convert_ir_to_dfg(ctx)

    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            if inst.opcode != "select":
                continue

            ret_op = inst.get_output_operands()[0]

            block_a = ctx.get_basic_block(inst.operands[0].value)
            block_b = ctx.get_basic_block(inst.operands[2].value)

            block_a.phi_vars[ret_op.value] = inst.operands[3]
            block_b.phi_vars[ret_op.value] = inst.operands[1]

    for i, bb in enumerate(ctx.basic_blocks):
        if i != 0:
            asm.append(f"_sym_{bb.label}")
            asm.append("JUMPDEST")

        fen = 0
        for inst in bb.instructions:
            inst.fen = fen
            if inst.opcode in ["call", "invoke", "sload", "sstore", "assert"]:
                fen += 1

        for inst in bb.instructions:
            asm = _generate_evm_for_instruction_r(ctx, asm, inst, stack_map)

    # Append postambles
    asm.extend(["_sym___revert", "JUMPDEST", *PUSH(0), "DUP1", "REVERT"])

    if no_optimize is False:
        optimize_assembly(asm)

    return assembly


# TODO: refactor this
label_counter = 0


def _generate_evm_for_instruction_r(
    ctx: IRFunction, assembly: list, inst: IRInstruction, stack_map: StackMap
) -> list[str]:
    global label_counter

    for op in inst.get_output_operands():
        for target in dfg_inputs.get(op.value, []):
            if target.parent != inst.parent:
                continue
            if target.fen != inst.fen:
                continue
            assembly = _generate_evm_for_instruction_r(ctx, assembly, target, stack_map)

    if inst in visited_instructions:
        return assembly
    visited_instructions.add(inst)

    # generate EVM for op
    opcode = inst.opcode
    operands = inst.get_input_operands()

    if opcode == "select":
        ret = inst.get_output_operands()[0]
        inputs = inst.get_input_variables()
        depth = stack_map.get_depth_in(inputs)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        to_be_replaced = stack_map.peek(depth)
        if to_be_replaced.use_count > 1:
            to_be_replaced.use_count -= 1
            stack_map.push(ret.target)
        else:
            stack_map.poke(depth, ret.target)
        return assembly

    _emit_input_operands(ctx, assembly, inst, stack_map)

    for op in operands:
        # final_stack_depth = -(len(operands) - i - 1)
        ucc = inst.get_use_count_correction(op)
        assert op.target.use_count >= ucc, "Operand used up"
        depth = stack_map.get_depth_in(op.target)
        assert depth != StackMap.NOT_IN_STACK, "Operand not in stack"
        needs_copy = op.target.use_count - ucc > 1
        if needs_copy:
            stack_map.dup(assembly, depth)
            op.target.use_count -= 1

    for i in range(len(operands)):
        op = operands[i]
        final_stack_depth = -(len(operands) - i - 1)
        depth = stack_map.get_depth_in(op.target)
        assert depth != StackMap.NOT_IN_STACK, "Operand not in stack"
        in_place_var = stack_map.peek(-final_stack_depth)
        is_in_place = in_place_var.value == op.target.value

        if not is_in_place:
            if final_stack_depth == 0 and depth != 0:
                stack_map.swap(assembly, depth)
            elif final_stack_depth != 0 and depth == 0:
                stack_map.swap(assembly, final_stack_depth)
            else:
                stack_map.swap(assembly, depth)
                stack_map.swap(assembly, final_stack_depth)

    stack_map.pop(len(operands))
    if inst.ret is not None:
        stack_map.push(inst.ret.target)

    if opcode in ONE_TO_ONE_INSTRUCTIONS:
        assembly.append(opcode.upper())
    elif opcode == "alloca":
        pass
    elif opcode == "store":
        pass
    elif opcode == "jnz":
        assembly.append(f"_sym_{inst.operands[1].value}")
        assembly.append("JUMPI")
    elif opcode == "jmp":
        if inst.operands[0].is_label:
            assembly.append(f"_sym_{inst.operands[0].value}")
            assembly.append("JUMP")
        else:
            assembly.append("JUMP")
    elif opcode == "gt":
        assembly.append("GT")
    elif opcode == "lt":
        assembly.append("LT")
    elif opcode == "invoke":
        target = inst.operands[0]
        assert target.is_label, "invoke target must be a label"
        assembly.extend(
            [
                f"_sym_label_ret_{label_counter}",
                f"_sym_{target.value}",
                "JUMP",
                f"_sym_label_ret_{label_counter}",
                "JUMPDEST",
            ]
        )
    elif opcode == "call":
        assembly.append("CALL")
    elif opcode == "ret":
        assert len(inst.operands) == 1, "ret instruction takes one operand"
        assembly.append("SWAP1")
        assembly.append("JUMP")
    elif opcode == "return":
        assembly.append("RETURN")
    elif opcode == "select":
        pass
    elif opcode == "sha3":
        assembly.append("SHA3")
    elif opcode == "sha3_64":
        assembly.extend(
            [
                *PUSH(MemoryPositions.FREE_VAR_SPACE2),
                "MSTORE",
                *PUSH(MemoryPositions.FREE_VAR_SPACE),
                "MSTORE",
                *PUSH(64),
                *PUSH(MemoryPositions.FREE_VAR_SPACE),
                "SHA3",
            ]
        )
    elif opcode == "ceil32":
        assembly.extend([*PUSH(31), "ADD", *PUSH(31), "NOT", "AND"])
    elif opcode == "assert":
        assembly.extend(["ISZERO", "_sym___revert", "JUMPI"])
    elif opcode == "deploy":
        memsize = inst.operands[0].value
        padding = inst.operands[2].value
        assembly.clear()
        assembly.extend(
            ["_sym_subcode_size", "_sym_runtime_begin", "_mem_deploy_start", "CODECOPY"]
        )
        assembly.extend(["_OFST", "_sym_subcode_size", padding])  # stack: len
        assembly.extend(["_mem_deploy_start"])  # stack: len mem_ofst
        assembly.extend(["RETURN"])
        assembly.append([RuntimeHeader("_sym_runtime_begin", memsize)])
        assembly = assembly[-1]
        pass
    else:
        raise Exception(f"Unknown opcode: {opcode}")

    if inst.ret is not None:
        assert inst.ret.is_variable, "Return value must be a variable"
        if inst.ret.target.mem_type == IRVariable.MemType.MEMORY:
            assembly.extend([*PUSH(inst.ret.target.mem_addr)])
            assembly.append("MSTORE")

    return assembly


def _emit_input_operands(
    ctx: IRFunction, assembly: list, inst: IRInstruction, stack_map: StackMap
) -> None:
    ops = inst.get_input_operands()
    for op in ops:
        if op.is_literal:
            assembly.extend([*PUSH(op.value)])
            stack_map.push(op.target)
            continue
        assembly = _generate_evm_for_instruction_r(ctx, assembly, dfg_outputs[op.value], stack_map)
        if op.is_variable and op.target.mem_type == IRVariable.MemType.MEMORY:
            if op.address_access:
                assembly.extend([*PUSH(op.addr)])
            else:
                assembly.extend([*PUSH(op.addr)])
                assembly.append("MLOAD")

    return assembly
