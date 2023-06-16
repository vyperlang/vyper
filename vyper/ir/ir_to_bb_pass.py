from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.codegen.ir_function import IRFunction, IRFunctionIntrinsic
from vyper.codegen.ir_basicblock import IRInstruction, IRDebugInfo
from vyper.codegen.ir_basicblock import IRBasicBlock
from vyper.evm.opcodes import get_opcodes

_symbols = {}

def convert_ir_basicblock(ctx: GlobalContext, ir):
    global_function = IRFunction("global")
    _convert_ir_basicblock(global_function, ir)
    return global_function

def _convert_binary_op(ctx: IRFunction, ir):
    arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
    arg_1 = _convert_ir_basicblock(ctx, ir.args[1])
    args = [arg_0, arg_1]

    ret = ctx.get_next_variable()

    inst = IRInstruction(ir.value, args, ret)
    ctx.get_basic_block().append_instruction(inst)
    return ret

def _convert_ir_basicblock(ctx: IRFunction, ir):
    if ir.value == "deploy":
        _convert_ir_basicblock(ctx, ir.args[1])
    elif ir.value == "seq":
        _convert_ir_seq_basicblock(ctx, ir.args)
    elif ir.value == "if":
        cond = ir.args[0]
        _convert_ir_basicblock(ctx, cond)
        _convert_ir_basicblock(ctx, ir.args[1])
    elif ir.value == "with":
        ret = _convert_ir_basicblock(ctx, ir.args[1])  # initialization

        sym = ir.args[0]
        # FIXME: How do I validate that the IR is indeed a symbol?
        _symbols[sym.value] = ctx.get_next_variable()

        inst = IRInstruction("load", [_symbols[sym.value], ret], None, 
                             IRDebugInfo(ir.source_pos, f"symbol: {sym.value}"))
        ctx.get_basic_block().append_instruction(inst)

        _convert_ir_basicblock(ctx, ir.args[2])  # body
    elif ir.value in ["le", "ge", "shr", "xor"]:
        return _convert_binary_op(ctx, ir)
    elif ir.value == "iszero":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])
        args = [arg_0]

        ret = ctx.get_next_variable()

        inst = IRInstruction("iszero", args, ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "goto":
        inst = IRInstruction("br", ir.args)
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "calldatasize":
        ret = ctx.get_next_variable()
        func = IRFunctionIntrinsic("calldatasize", [])
        inst = IRInstruction("call", [func], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "calldataload":
        ret = ctx.get_next_variable()
        func = IRFunctionIntrinsic("calldataload", [ir.args[0]])
        inst = IRInstruction("call", [func], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "callvalue":
        ret = ctx.get_next_variable()
        func = IRFunctionIntrinsic("callvalue", [])
        inst = IRInstruction("call", [func], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "assert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0])

        ret = ctx.get_next_variable()
        func = IRFunctionIntrinsic("assert", [arg_0])
        inst = IRInstruction("call", [func], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "label":
        label = ir.args[0]
        bb = IRBasicBlock(label, ctx)
        ctx.append_basic_block(bb)        
        _convert_ir_basicblock(ctx, ir.args[2])
    elif ir.value == "return":
        pass    
    elif ir.value == "exit_to":
        pass
    elif ir.value == "pass":
        pass    
    elif isinstance(ir.value, str) and ir.value.upper() in get_opcodes():
        _convert_ir_opcode(ctx, ir)
    elif isinstance(ir.value, str) and ir.value in _symbols:
        return _symbols[ir.value]
    elif ir.is_literal:
        return ir.value
    else:
        raise Exception(f"Unknown IR node: {ir}")


def _convert_ir_opcode(ctx: IRFunction, ir: IRnode):
    opcode = ir.value.upper()
    for arg in ir.args:
        if isinstance(arg, IRnode):
            _convert_ir_basicblock(ctx, arg)
    instruction = IRInstruction(opcode, ir.args)
    ctx.get_basic_block().append_instruction(instruction)
    pass


def _convert_ir_seq_basicblock(ctx: IRFunction, seq_args: list[IRnode]):
    bb = IRBasicBlock(ctx.get_next_label(), ctx)
    ctx.append_basic_block(bb)

    for ir_node in seq_args:
        _convert_ir_basicblock(ctx, ir_node)
