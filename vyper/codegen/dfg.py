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


def convert_ir_to_dfg(ctx: IRFunction) -> None:
    # Reset DFG
    ctx.dfg_inputs = {}
    ctx.dfg_outputs = {}
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            inst.dup_requirements = OrderedSet()
            inst.fen = -1
            operands = inst.get_input_operands()
            operands.extend(inst.get_output_operands())

    # Build DFG
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            operands = inst.get_input_operands()
            res = inst.get_output_operands()

            for op in operands:
                ctx.dfg_inputs[op.value] = (
                    [inst]
                    if ctx.dfg_inputs.get(op.value) is None
                    else ctx.dfg_inputs[op.value] + [inst]
                )

            for op in res:
                ctx.dfg_outputs[op.value] = inst

    # Build DUP requirements
    _compute_dup_requirements(ctx)


def _compute_inst_dup_requirements_r(
    ctx: IRFunction, inst: IRInstruction, visited: OrderedSet, last_seen: dict
):
    for op in inst.get_output_operands():
        for target in ctx.dfg_inputs.get(op.value, []):
            if target.parent != inst.parent:
                continue
            if target.fen != inst.fen:
                continue
            _compute_inst_dup_requirements_r(ctx, target, visited, last_seen)

    if inst in visited:
        return
    visited.add(inst)

    if inst.opcode == "select":
        return

    for op in inst.get_input_operands():
        target = ctx.dfg_outputs[op.value]
        if target.parent != inst.parent:
            continue
        old_last_seen = last_seen.copy()
        _compute_inst_dup_requirements_r(ctx, target, visited, last_seen)

    for op in inst.get_input_operands():
        l = last_seen.get(op.value, None)
        if l:
            l.dup_requirements.add(op)
        last_seen[op.value] = inst

    return


def _compute_dup_requirements(ctx: IRFunction) -> None:
    fen = 0
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            inst.fen = fen
            if inst.volatile:
                fen += 1

        visited = OrderedSet()
        last_seen = {}
        for inst in bb.instructions:
            _compute_inst_dup_requirements_r(ctx, inst, visited, last_seen)

        out_vars = bb.out_vars
        for inst in bb.instructions[::-1]:
            for op in inst.get_input_operands():
                if op in out_vars:
                    inst.dup_requirements.add(op)


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


def _stack_duplications(
    assembly: list,
    dep_liveness: OrderedSet[IRValueBase],
    inst: IRInstruction,
    stack_map: StackMap,
    stack_ops: list[IRValueBase],
) -> None:
    last_used = inst.parent.get_last_used_operands(inst)
    for op in stack_ops:
        if op.is_literal or isinstance(op, IRLabel):
            continue
        depth = stack_map.get_depth_in(op)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        if op in inst.dup_requirements:
            stack_map.dup(assembly, depth)


def __stack_duplications(
    assembly: list,
    dep_liveness: OrderedSet[IRValueBase],
    inst: IRInstruction,
    stack_map: StackMap,
    stack_ops: list[IRValueBase],
) -> None:
    last_used = inst.liveness.difference(dep_liveness)
    for op in stack_ops:
        if op.is_literal or isinstance(op, IRLabel):
            continue
        depth = stack_map.get_depth_in(op)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        if op not in last_used:
            stack_map.dup(assembly, depth)


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
    ctx: IRFunction,
    asm: list,
    basicblock: IRBasicBlock,
    stack_map: StackMap,
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

    for idx, inst in enumerate(basicblock.instructions):
        # orig_inst = (
        #     basicblock.instructions[idx + 1] if idx + 1 < len(basicblock.instructions) else None
        # )
        asm, _ = _generate_evm_for_instruction_r(ctx, asm, inst, stack_map)

    for bb in basicblock.out_set:
        _generate_evm_for_basicblock_r(ctx, asm, bb, stack_map.copy())

    return asm


# TODO: refactor this
label_counter = 0


def _generate_evm_for_instruction_r(
    ctx: IRFunction,
    assembly: list,
    inst: IRInstruction,
    stack_map: StackMap,
) -> (list[str], IRInstruction):
    global label_counter

    origin_inst = None
    for op in inst.get_output_operands():
        for target in ctx.dfg_inputs.get(op.value, []):
            if target.parent != inst.parent:
                continue
            if target.fen != inst.fen:
                continue
            assembly, origin_inst = _generate_evm_for_instruction_r(
                ctx, assembly, target, stack_map
            )

    if origin_inst is None:
        if inst.opcode in ["jmp", "jnz"]:
            origin_inst = OrderedSet()
            for bb in inst.parent.out_set:
                l = bb.in_vars_for(inst.parent)
                origin_inst |= l
        else:
            next_inst = inst.parent.get_next_instruction(inst)
            origin_inst = next_inst.liveness if next_inst else OrderedSet()

    if inst in visited_instructions:
        return assembly, inst.liveness
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
    elif opcode == "iload":
        operands = []
    elif opcode == "istore":
        operands = inst.operands[0:1]
    else:
        operands = inst.operands

    if opcode == "select":
        ret = inst.get_output_operands()[0]
        inputs = inst.get_input_operands()
        depth = stack_map.get_depth_in(inputs)
        assert depth is not StackMap.NOT_IN_STACK, "Operand not in stack"
        to_be_replaced = stack_map.peek(depth)
        if to_be_replaced in inst.dup_requirements:
            stack_map.dup(assembly, depth)
            stack_map.poke(0, ret)
        else:
            stack_map.poke(depth, ret)
        return assembly, inst

    # Step 2: Emit instruction's input operands
    _emit_input_operands(ctx, assembly, inst, operands, stack_map)

    # Step 3: Reorder stack
    if opcode in ["jnz", "jmp"]:  # and stack_map.get_height() >= 2:
        _, b = next(enumerate(inst.parent.out_set))
        t_liveness = b.in_vars_for(inst.parent)
        target_stack = OrderedSet(t_liveness)  # [b.phi_vars.get(v.value, v) for v in t_liveness]
        current_stack = OrderedSet(stack_map.stack_map)
        # if opcode == "jmp":
        #     need_pop = current_stack.difference(target_stack)
        #     for op in need_pop:
        #         if op.use_count > 0:
        #             continue
        #         depth = stack_map.get_depth_in(op)
        #         if depth is StackMap.NOT_IN_STACK:
        #             continue
        #         if depth != 0:
        #             stack_map.swap(assembly, depth)
        #         stack_map.pop()
        #         assembly.append("POP")
        phi_mappings = inst.parent.get_phi_mappings()
        _stack_reorder(assembly, stack_map, target_stack, phi_mappings)

    liveness = origin_inst if origin_inst else OrderedSet()
    _stack_duplications(assembly, liveness, inst, stack_map, operands)
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
        if stack_map.get_height() > 0 and stack_map.peek(0) in inst.dup_requirements:
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
    elif opcode == "iload":
        loc = inst.operands[0].value
        assembly.extend(["_OFST", "_mem_deploy_end", loc, "MLOAD"])
    elif opcode == "istore":
        loc = inst.operands[1].value
        assembly.extend(["_OFST", "_mem_deploy_end", loc, "MSTORE"])
    else:
        raise Exception(f"Unknown opcode: {opcode}")

    # Step 6: Emit instructions output operands (if any)
    if inst.ret is not None:
        assert isinstance(inst.ret, IRVariable), "Return value must be a variable"
        if inst.ret.mem_type == IRVariable.MemType.MEMORY:
            assembly.extend([*PUSH(inst.ret.mem_addr)])

    return assembly, inst.liveness


def _emit_input_operands(
    ctx: IRFunction,
    assembly: list,
    inst: IRInstruction,
    ops: list[IRValueBase],
    stack_map: StackMap,
) -> OrderedSet[IRValueBase]:
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
        assembly, origin_inst = _generate_evm_for_instruction_r(
            ctx, assembly, ctx.dfg_outputs[op.value], stack_map
        )
        if isinstance(op, IRVariable) and op.mem_type == IRVariable.MemType.MEMORY:
            assembly.extend([*PUSH(op.mem_addr)])
            assembly.append("MLOAD")

    return
