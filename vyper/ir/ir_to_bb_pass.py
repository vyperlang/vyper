from typing import Optional, Union
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen.ir_function import IRFunctionBase, IRFunction, IRFunctionIntrinsic
from vyper.codegen.ir_basicblock import IRInstruction, IRDebugInfo
from vyper.codegen.ir_basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.evm.opcodes import get_opcodes

_symbols = {}


def convert_ir_basicblock(ctx: GlobalContext, ir: IRnode) -> IRFunction:
    global_function = IRFunction("global")
    _convert_ir_basicblock(global_function, ir)
    while _optimize_empty_basicblocks(global_function):
        pass
    _optimize_unused_variables(global_function)
    return global_function


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
                        op.label = replacement_label

        ctx.basic_blocks.remove(bb)
        i -= 1
        count += 1

    return count


def _optimize_unused_variables(ctx: IRFunction) -> None:
    """
    Remove unused variables.
    """
    count = 0
    uses = {}
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            for op in inst.operands:
                if isinstance(op, IRVariable):
                    uses[op] = uses.get(op, 0) + 1
                elif isinstance(op, IRFunctionBase):
                    for arg in op.args:
                        if isinstance(arg, IRVariable):
                            uses[arg] = uses.get(arg, 0) + 1

    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            if inst.ret is None:
                continue

            if inst.ret in uses:
                continue

            print("Removing unused variable: %s" % inst.ret)

    print(uses)
    return count


def _convert_binary_op(ctx: IRFunction, ir: IRnode) -> str:
    arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
    arg_1 = _convert_ir_basicblock(ctx, ir.args[1])
    args = [arg_0, arg_1]

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
        if len(ir.args) == 3:
            _convert_ir_basicblock(ctx, ir.args[2])

        # convert "then"
        then_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(then_block)

        _convert_ir_basicblock(ctx, ir.args[1])

        inst = IRInstruction("br", [cont_ret, then_block.label, else_block.label])
        current_bb.append_instruction(inst)

        # exit bb
        exit_label = ctx.get_next_label()
        bb = IRBasicBlock(exit_label, ctx)
        bb = ctx.append_basic_block(bb)

        exit_inst = IRInstruction("br", [bb.label])
        else_block.append_instruction(exit_inst)

        then_block.add_in(current_bb)
        else_block.add_in(current_bb)
        bb.add_in(then_block)
        bb.add_in(else_block)

    elif ir.value == "with":
        ret = _convert_ir_basicblock(ctx, ir.args[1])  # initialization

        sym = ir.args[0]
        # FIXME: How do I validate that the IR is indeed a symbol?
        _symbols[sym.value] = ret
        # first_pos = ir.source_pos[0] if ir.source_pos else None
        # inst = IRInstruction(
        #     "load",
        #     [ret],
        #     _symbols[sym.value],
        #     IRDebugInfo(first_pos or 0, f"symbol: {sym.value}"),
        # )
        # ctx.get_basic_block().append_instruction(inst)

        return _convert_ir_basicblock(ctx, ir.args[2])  # body
    elif ir.value in ["eq", "le", "ge", "gt", "shr", "or", "xor", "add", "sub", "mul", "div", "mod"]:
        return _convert_binary_op(ctx, ir)
    elif ir.value == "iszero":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
        args = [arg_0]

        ret = ctx.get_next_variable()

        inst = IRInstruction("iszero", args, ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "goto":
        inst = IRInstruction("br", [IRLabel(ir.args[0].value)])
        ctx.get_basic_block().append_instruction(inst)

        label = ctx.get_next_label()
        bb = IRBasicBlock(label, ctx)
        bb.add_in(ctx.get_basic_block())
        ctx.append_basic_block(bb)
    elif ir.value == "calldatasize":
        ret = ctx.get_next_variable()
        inst = IRInstruction("calldatasize", [], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "calldataload":
        ret = ctx.get_next_variable()
        inst = IRInstruction("calldataload", [ir.args[0].value], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "callvalue":
        ret = ctx.get_next_variable()
        inst = IRInstruction("callvalue", [], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "assert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
        func = IRFunctionIntrinsic("assert", [arg_0])
        inst = IRInstruction("call", [func])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "label":
        bb = IRBasicBlock(IRLabel(ir.args[0].value, True), ctx)
        ctx.append_basic_block(bb)
        _convert_ir_basicblock(ctx, ir.args[2])
    elif ir.value == "return":
        pass
    elif ir.value == "exit_to":
        ret = _convert_ir_basicblock(ctx, ir.args[2])

        # for now
        inst = IRInstruction("ret", [ret])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "revert":
        func = IRFunctionIntrinsic("revert", ir.args)
        inst = IRInstruction("call", [func])
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
        return ir.value
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
