from vyper.codegen.ir_basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRVariable,
    IRValueBase,
    IRLabel,
)
from vyper.codegen.ir_function import IRFunction
from vyper.compiler.utils import StackMap
from vyper.ir.compile_ir import PUSH, DataHeader, RuntimeHeader, optimize_assembly
from vyper.utils import MemoryPositions, OrderedSet

ONE_TO_ONE_INSTRUCTIONS = [
    "revert",
    "coinbase",
    "calldatasize",
    "calldatacopy",
    "calldataload",
    "gas",
    "gasprice",
    "gaslimit",
    "address",
    "origin",
    "number",
    "extcodesize",
    "extcodehash",
    "returndatasize",
    "returndatacopy",
    "callvalue",
    "selfbalance",
    "sload",
    "sstore",
    "mload",
    "mstore",
    "timestamp",
    "caller",
    "selfdestruct",
    "signextend",
    "stop",
    "shr",
    "shl",
    "and",
    "xor",
    "or",
    "add",
    "sub",
    "mul",
    "div",
    "mod",
    "exp",
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


class DFGNode:
    value: IRInstruction | IRValueBase
    predecessors: list["DFGNode"]
    successors: list["DFGNode"]

    def __init__(self, value: IRInstruction | IRValueBase):
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
            operands = inst.get_input_operands()
            res = inst.get_output_operands()

            for op in operands:
                op.use_count += 1
                dfg_inputs[op.value] = (
                    [inst] if dfg_inputs.get(op.value) is None else dfg_inputs[op.value] + [inst]
                )

            for op in res:
                dfg_outputs[op.value] = inst


def compute_phi_vars(ctx: IRFunction) -> None:
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            if inst.opcode != "select":
                continue

            ret_op = inst.get_output_operands()[0]

            block_a = ctx.get_basic_block(inst.operands[0].value)
            block_b = ctx.get_basic_block(inst.operands[2].value)

            block_a.phi_vars[inst.operands[1].value] = ret_op
            block_a.phi_vars[inst.operands[3].value] = ret_op
            block_b.phi_vars[inst.operands[1].value] = ret_op
            block_b.phi_vars[inst.operands[3].value] = ret_op


visited_instructions = {IRInstruction}
visited_basicblocks = {IRBasicBlock}


def generate_evm(ctx: IRFunction, no_optimize: bool = False) -> list[str]:
    global visited_instructions, visited_basicblocks
    asm = []
    visited_instructions = set()
    visited_basicblocks = set()

    convert_ir_to_dfg(ctx)
    compute_phi_vars(ctx)

    _generate_evm_for_basicblock_r(ctx, asm, ctx.basic_blocks[0], StackMap())

    # Append postambles
    revert_postamble = ["_sym___revert", "JUMPDEST", *PUSH(0), "DUP1", "REVERT"]
    runtime = None
    if isinstance(asm[-1], list) and isinstance(asm[-1][0], RuntimeHeader):
        runtime = asm.pop()

    asm.extend(revert_postamble)
    if runtime:
        runtime.extend(revert_postamble)
        asm.append(runtime)

    # Append data segment
    data_segments = {}
    for inst in ctx.data_segment:
        if inst.opcode == "dbname":
            label = inst.operands[0].value
            data_segments[label] = [DataHeader(f"_sym_{label}")]
        elif inst.opcode == "db":
            data_segments[label].append(f"_sym_{inst.operands[0].value}")

    extent_point = asm if not isinstance(asm[-1], list) else asm[-1]
    extent_point.extend([data_segments[label] for label in data_segments])

    if no_optimize is False:
        optimize_assembly(asm)

    return asm


def _stack_duplications(assembly: list, stack_map: StackMap, stack_ops: list[IRValueBase]) -> None:
    for op in stack_ops:
        assert op.use_count >= 0, "Operand used up"
        depth = stack_map.get_depth_in(op)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        if op.use_count > 1:
            # Operand need duplication
            stack_map.dup(assembly, depth)
            op.use_count -= 1


def _stack_reorder(
    assembly: list, stack_map: StackMap, stack_ops: list[IRValueBase], phi_vars: dict = {}
) -> None:
    def f(x):
        return phi_vars.get(str(x), x)

    stack_ops = [f(x.value) for x in stack_ops]
    for i in range(len(stack_ops)):
        op = stack_ops[i]
        final_stack_depth = -(len(stack_ops) - i - 1)
        depth = stack_map.get_depth_in(op, phi_vars)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        is_in_place = depth == final_stack_depth

        if not is_in_place:
            if final_stack_depth == 0 and depth != 0:
                stack_map.swap(assembly, depth)
            elif final_stack_depth != 0 and depth == 0:
                stack_map.swap(assembly, final_stack_depth)
            else:
                stack_map.swap(assembly, depth)
                stack_map.swap(assembly, final_stack_depth)


def _generate_evm_for_basicblock_r(
    ctx: IRFunction, asm: list, basicblock: IRBasicBlock, stack_map: StackMap
):
    if basicblock in visited_basicblocks:
        return
    visited_basicblocks.add(basicblock)

    asm.append(f"_sym_{basicblock.label}")
    asm.append("JUMPDEST")

    # values to pop from stack
    in_vars = OrderedSet()
    for in_bb in basicblock.in_set:
        in_vars |= in_bb.out_vars.difference(basicblock.in_vars_for(in_bb))

    for var in in_vars:
        depth = stack_map.get_depth_in(IRValueBase(var.value))
        if depth is StackMap.NOT_IN_STACK:
            continue
        if depth != 0:
            stack_map.swap(asm, depth)
        stack_map.pop()
        asm.append("POP")

    fen = 0
    for inst in basicblock.instructions:
        inst.fen = fen
        if inst.volatile:
            fen += 1

    for inst in basicblock.instructions:
        asm = _generate_evm_for_instruction_r(ctx, asm, inst, stack_map)

    for bb in basicblock.out_set:
        _generate_evm_for_basicblock_r(ctx, asm, bb, stack_map.copy())

    return asm


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

    opcode = inst.opcode

    #
    # generate EVM for op
    #

    # Step 1: Apply instruction special stack manipulations

    if opcode in ["jmp", "jnz", "invoke"]:
        operands = inst.get_non_label_operands()
    elif opcode == "alloca":
        operands = inst.operands[1:2]
    else:
        operands = inst.operands

    if opcode == "select":
        ret = inst.get_output_operands()[0]
        inputs = inst.get_input_operands()
        depth = stack_map.get_depth_in(inputs)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        to_be_replaced = stack_map.peek(depth)
        if to_be_replaced.use_count > 1:
            stack_map.dup(assembly, depth)
            to_be_replaced.use_count -= 1
            stack_map.poke(0, ret)
        else:
            stack_map.poke(depth, ret)
        return assembly

    # Step 2: Emit instructions input operands
    _emit_input_operands(ctx, assembly, inst, operands, stack_map)

    # Step 3: Reorder stack
    if opcode in ["jnz", "jmp"] and stack_map.get_height() >= 2:
        _, b = next(enumerate(inst.parent.out_set))
        target_stack = b.get_liveness()
        _stack_reorder(assembly, stack_map, target_stack, inst.parent.phi_vars)

    _stack_duplications(assembly, stack_map, operands)
    _stack_reorder(assembly, stack_map, operands)

    # Step 4: Push instruction's return value to stack
    stack_map.pop(len(operands))
    if inst.ret is not None:
        stack_map.push(inst.ret)

    # Step 5: Emit the EVM instruction(s)
    if opcode in ONE_TO_ONE_INSTRUCTIONS:
        assembly.append(opcode.upper())
    elif opcode == "alloca":
        pass
    elif opcode == "param":
        pass
    elif opcode == "store":
        pass
    elif opcode == "dbname":
        pass
    elif opcode in ["codecopy", "dloadbytes"]:
        assembly.append("CODECOPY")
    elif opcode == "jnz":
        assembly.append(f"_sym_{inst.operands[1].value}")
        assembly.append("JUMPI")
    elif opcode == "jmp":
        if isinstance(inst.operands[0], IRLabel):
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
        assert isinstance(target, IRLabel), "invoke target must be a label"
        assembly.extend(
            [
                f"_sym_label_ret_{label_counter}",
                f"_sym_{target.value}",
                "JUMP",
                f"_sym_label_ret_{label_counter}",
                "JUMPDEST",
            ]
        )
        label_counter += 1
        if stack_map.get_height() > 0 and stack_map.peek(0).use_count == 0:
            stack_map.pop()
            assembly.append("POP")
    elif opcode == "call":
        assembly.append("CALL")
    elif opcode == "staticcall":
        assembly.append("STATICCALL")
    elif opcode == "ret":
        # assert len(inst.operands) == 2, "ret instruction takes two operands"
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
        # TODO: fix this by removing deploy opcode altogether me move emition to ir translation
        while assembly[-1] != "JUMPDEST":
            assembly.pop()
        assembly.extend(
            ["_sym_subcode_size", "_sym_runtime_begin", "_mem_deploy_start", "CODECOPY"]
        )
        assembly.extend(["_OFST", "_sym_subcode_size", padding])  # stack: len
        assembly.extend(["_mem_deploy_start"])  # stack: len mem_ofst
        assembly.extend(["RETURN"])
        assembly.append([RuntimeHeader("_sym_runtime_begin", memsize, padding)])
        assembly = assembly[-1]
        pass
    else:
        raise Exception(f"Unknown opcode: {opcode}")

    # Step 6: Emit instructions output operands (if any)
    # FIXME: WHOLE THING NEEDS REFACTOR
    if inst.ret is not None:
        assert isinstance(inst.ret, IRVariable), "Return value must be a variable"
        if inst.ret.mem_type == IRVariable.MemType.MEMORY:
            #     # if inst.ret.address_access:                           FIXME: MEMORY REFACTOR
            #     #     if inst.opcode != "alloca":  # FIXMEEEE
            #     #         if inst.opcode != "codecopy":
            #     #             assembly.extend([*PUSH(inst.ret.addr)])
            #     #     else:
            #     assembly.extend([*PUSH(inst.ret.mem_addr + 30)])
            # else:
            assembly.extend([*PUSH(inst.ret.mem_addr)])
        # assembly.append("MSTORE")

    return assembly


def _emit_input_operands(
    ctx: IRFunction,
    assembly: list,
    inst: IRInstruction,
    ops: list[IRValueBase],
    stack_map: StackMap,
) -> None:
    for op in ops:
        if isinstance(op, IRLabel):
            # invoke emits the actual instruction itself so we don't need to emit it here
            # but we need to add it to the stack map
            if inst.opcode != "invoke":
                assembly.append(f"_sym_{op.value}")
            stack_map.push(op)
            continue
        if op.is_literal:
            assembly.extend([*PUSH(op.value)])
            stack_map.push(op)
            continue
        assembly = _generate_evm_for_instruction_r(ctx, assembly, dfg_outputs[op.value], stack_map)
        if isinstance(op, IRVariable) and op.mem_type == IRVariable.MemType.MEMORY:
            # FIXME: MEMORY REFACTOR
            # if op.address_access:
            #     if inst.opcode != "codecopy":
            #         assembly.extend([*PUSH(op.addr)])
            # else:
            assembly.extend([*PUSH(op.mem_addr)])
            assembly.append("MLOAD")

    return assembly
