from typing import Optional, Union
from vyper.codegen.dfg import convert_ir_to_dfg, generate_evm
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen.ir_function import IRFunctionBase, IRFunction, IRFunctionIntrinsic
from vyper.codegen.ir_basicblock import IRInstruction, IRDebugInfo
from vyper.codegen.ir_basicblock import IRBasicBlock, IRLabel, IRLiteral
from vyper.evm.opcodes import get_opcodes

TERMINATOR_IR_INSTRUCTIONS = [
    "jmp",
    "jnz",
    "ret",
    "revert",
]

_symbols = {}


def _get_symbols_common(a: dict, b: dict) -> dict:
    return {k: [a[k], b[k]] for k in a.keys() & b.keys() if a[k] != b[k]}


def generate_assembly_experimental(ir: IRnode) -> list[str]:
    global_function = convert_ir_basicblock(ir)
    return generate_evm(global_function)


def convert_ir_basicblock(ir: IRnode) -> IRFunction:
    global_function = IRFunction(IRLabel("global"))
    _convert_ir_basicblock(global_function, ir)

    revert_bb = IRBasicBlock(IRLabel("__revert"), global_function)
    revert_bb = global_function.append_basic_block(revert_bb)
    revert_bb.append_instruction(IRInstruction("revert", [IRLiteral(0), IRLiteral(0)]))

    while _optimize_empty_basicblocks(global_function):
        pass

    # TODO: can be split into a new pass
    _calculate_in_set(global_function)
    _calculate_liveness(global_function.basic_blocks[0])

    # Optimization pass: Remove unused variables
    _optimize_unused_variables(global_function)

    return global_function


def _optimize_unused_variables(ctx: IRFunction) -> int:
    """
    Remove unused variables.
    """
    count = 0
    removeList = []
    for bb in ctx.basic_blocks:
        for i, inst in enumerate(bb.instructions[:-1]):
            if inst.ret and inst.ret not in bb.instructions[i + 1].liveness:
                removeList.append(inst)
                count += 1

        bb.instructions = [inst for inst in bb.instructions if inst not in removeList]

    return count


def _optimize_empty_basicblocks(ctx: IRFunction) -> None:
    """
    Remove empty basic blocks.
    """
    count = 0
    i = 0
    while i < len(ctx.basic_blocks):
        bb = ctx.basic_blocks[i]
        i += 1
        if len(bb.instructions) > 0:
            continue

        replaced_label = bb.label
        replacement_label = ctx.basic_blocks[i].label if i < len(ctx.basic_blocks) else None
        if replacement_label is None:
            continue

        # Try to preserve symbol labels
        if replaced_label.is_symbol:
            replaced_label, replacement_label = replacement_label, replaced_label
            ctx.basic_blocks[i].label = replacement_label

        for bb2 in ctx.basic_blocks:
            for inst in bb2.instructions:
                for op in inst.operands:
                    if isinstance(op, IRLabel) and op == replaced_label:
                        op.value = replacement_label.value

        ctx.basic_blocks.remove(bb)
        i -= 1
        count += 1

    return count


def _calculate_in_set(ctx: IRFunction) -> None:
    """
    Calculate in set for each basic block.
    """
    for bb in ctx.basic_blocks:
        assert len(bb.instructions) > 0, "Basic block should not be empty"
        last_inst = bb.instructions[-1]
        assert (
            last_inst.opcode in TERMINATOR_IR_INSTRUCTIONS
        ), "Last instruction should be a terminator"

        if last_inst.opcode in ["jmp", "jnz"]:
            ops = last_inst.get_label_operands()
            assert len(ops) >= 1, "branch instruction should have at least one label operand"
            for op in ops:
                ctx.get_basic_block(op.value).add_in(bb)

    # Fill in the "out" set for each basic block
    for bb in ctx.basic_blocks:
        for in_bb in bb.in_set:
            in_bb.add_out(bb)


liveness_visited = set()


def _calculate_liveness(bb: IRBasicBlock) -> None:
    for out_bb in bb.out_set:
        _calculate_liveness(out_bb)
        in_vars = out_bb.in_vars_for(bb)
        bb.out_vars = bb.out_vars.union(in_vars)

    if bb in liveness_visited:
        return
    liveness_visited.add(bb)
    bb.calculate_liveness()


def _convert_binary_op(ctx: IRFunction, ir: IRnode, swap: bool = False) -> str:
    ir_args = ir.args[::-1] if swap else ir.args
    arg_0 = _convert_ir_basicblock(ctx, ir_args[0])
    arg_1 = _convert_ir_basicblock(ctx, ir_args[1])
    args = [arg_1, arg_0]

    ret = ctx.get_next_variable()

    inst = IRInstruction(str(ir.value), args, ret)
    ctx.get_basic_block().append_instruction(inst)
    return ret


def _convert_ir_basicblock(ctx: IRFunction, ir: IRnode) -> Optional[Union[str, int]]:
    if ir.value == "deploy":
        _convert_ir_basicblock(ctx, ir.args[1])
    elif ir.value == "seq":
        ret = None
        for ir_node in ir.args:  # NOTE: skip the last one
            r = _convert_ir_basicblock(ctx, ir_node)
            if ir_node.is_literal == False:
                ret = r
        return ret
    elif ir.value == "if":
        cond = ir.args[0]
        current_bb = ctx.get_basic_block()

        # convert the condition
        cont_ret = _convert_ir_basicblock(ctx, cond)

        else_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(else_block)

        # convert "else"
        start_syms = _symbols.copy()
        if len(ir.args) == 3:
            _convert_ir_basicblock(ctx, ir.args[2])
        after_else_syms = _symbols.copy()

        # convert "then"
        then_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(then_block)

        _convert_ir_basicblock(ctx, ir.args[1])

        inst = IRInstruction("jnz", [cont_ret, then_block.label, else_block.label])
        current_bb.append_instruction(inst)

        after_then_syms = _symbols.copy()

        # exit bb
        exit_label = ctx.get_next_label()
        bb = IRBasicBlock(exit_label, ctx)
        bb = ctx.append_basic_block(bb)

        for sym, val in _get_symbols_common(after_then_syms, after_else_syms).items():
            ret = ctx.get_next_variable()
            _symbols[sym] = ret
            bb.append_instruction(
                IRInstruction("select", [then_block.label, val[0], else_block.label, val[1]], ret)
            )

        exit_inst = IRInstruction("jmp", [bb.label])
        else_block.append_instruction(exit_inst)

    elif ir.value == "with":
        ret = _convert_ir_basicblock(ctx, ir.args[1])  # initialization

        sym = ir.args[0]
        # FIXME: How do I validate that the IR is indeed a symbol?
        _symbols[sym.value] = ret

        return _convert_ir_basicblock(ctx, ir.args[2])  # body
    elif ir.value in [
        "eq",
        "gt",
        "lt",
        "slt",
        "sgt",
        "shr",
        "or",
        "xor",
        "add",
        "sub",
        "mul",
        "div",
        "mod",
    ]:
        return _convert_binary_op(ctx, ir, ir.value in [])
    elif ir.value == "le":
        ir.value = "gt"
        return _convert_binary_op(ctx, ir, False)  # TODO: check if this is correct order
    elif ir.value == "ge":
        ir.value = "lt"
        return _convert_binary_op(ctx, ir, False)  # TODO: check if this is correct order
    elif ir.value == "iszero":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
        args = [arg_0]

        ret = ctx.get_next_variable()

        inst = IRInstruction("iszero", args, ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "goto":
        inst = IRInstruction("jmp", [IRLabel(ir.args[0].value)])
        ctx.get_basic_block().append_instruction(inst)

        label = ctx.get_next_label()
        bb = IRBasicBlock(label, ctx)
        ctx.append_basic_block(bb)
    elif ir.value == "calldatasize":
        ret = ctx.get_next_variable()
        inst = IRInstruction("calldatasize", [], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "calldataload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
        ret = ctx.get_next_variable()
        inst = IRInstruction("calldataload", [arg_0], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "callvalue":
        ret = ctx.get_next_variable()
        inst = IRInstruction("callvalue", [], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "assert":
        current_bb = ctx.get_basic_block()
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])

        exit_label = ctx.get_next_label()
        bb = IRBasicBlock(exit_label, ctx)
        bb = ctx.append_basic_block(bb)

        inst = IRInstruction("jnz", [arg_0, IRLabel("__revert"), exit_label])
        current_bb.append_instruction(inst)

    elif ir.value == "label":
        bb = IRBasicBlock(IRLabel(ir.args[0].value, True), ctx)
        ctx.append_basic_block(bb)
        _convert_ir_basicblock(ctx, ir.args[2])
    elif ir.value == "return":
        pass
    elif ir.value == "exit_to":
        arg_2 = _convert_ir_basicblock(ctx, ir.args[2])
        sym = ir.args[1]
        new_var = _symbols.get(f"&{sym.value}", arg_2)
        assert new_var != None, "exit_to with undefined variable"
        inst = IRInstruction("ret", [new_var])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "revert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1])
        inst = IRInstruction("revert", [arg_0, arg_1])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "pass":
        pass
    elif ir.value == "mload":
        sym = ir.args[0]
        new_var = _symbols.get(f"&{sym.value}", None)
        assert new_var != None, "mload without mstore"
        return new_var
    elif ir.value == "mstore":
        sym = ir.args[0]
        new_var = _convert_ir_basicblock(ctx, ir.args[1])
        _symbols[f"&{sym.value}"] = new_var
        return new_var
    elif isinstance(ir.value, str) and ir.value.upper() in get_opcodes():
        _convert_ir_opcode(ctx, ir)
    elif isinstance(ir.value, str) and ir.value in _symbols:
        return _symbols[ir.value]
    elif ir.is_literal:
        return IRLiteral(ir.value)
    else:
        raise Exception(f"Unknown IR node: {ir}")

    return None


def _convert_ir_opcode(ctx: IRFunction, ir: IRnode) -> None:
    opcode = str(ir.value).upper()
    for arg in ir.args:
        if isinstance(arg, IRnode):
            _convert_ir_basicblock(ctx, arg)
    instruction = IRInstruction(opcode, ir.args)
    ctx.get_basic_block().append_instruction(instruction)
