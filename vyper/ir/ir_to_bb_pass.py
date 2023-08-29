from typing import Optional, Union

from vyper.codegen.dfg import generate_evm
from vyper.codegen.ir_basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IRValueBase,
    IRVariable,
    IROperand,
)
from vyper.codegen.ir_function import IRFunction
from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.evm.opcodes import get_opcodes
from vyper.ir.bb_optimizer import optimize_function
from vyper.semantics.types.function import ContractFunctionT

BINARY_IR_INSTRUCTIONS = [
    "eq",
    "gt",
    "lt",
    "slt",
    "sgt",
    "shr",
    "shl",
    "or",
    "xor",
    "and",
    "add",
    "sub",
    "mul",
    "div",
    "mod",
    "sha3",
    "sha3_64",
]

MAPPED_IR_INSTRUCTIONS = {"le": "gt", "sle": "sgt", "ge": "lt", "sge": "slt"}

SymbolTable = dict[str, IRValueBase]


def _get_symbols_common(a: dict, b: dict) -> dict:
    return {k: [a[k], b[k]] for k in a.keys() & b.keys() if a[k] != b[k]}


def generate_assembly_experimental(
    ir: IRnode, optimize: Optional[OptimizationLevel] = None
) -> list[str]:
    global_function = convert_ir_basicblock(ir)
    return generate_evm(global_function, optimize is OptimizationLevel.NONE)


def convert_ir_basicblock(ir: IRnode, optimize: Optional[OptimizationLevel] = None) -> IRFunction:
    global_function = IRFunction(IRLabel("global"))
    _convert_ir_basicblock(global_function, ir, {})

    revert_bb = IRBasicBlock(IRLabel("__revert"), global_function)
    revert_bb = global_function.append_basic_block(revert_bb)
    revert_bb.append_instruction(IRInstruction("revert", [IRLiteral(0), IRLiteral(0)]))

    if optimize is not OptimizationLevel.NONE:
        optimize_function(global_function)

    return global_function


def _convert_binary_op(
    ctx: IRFunction, ir: IRnode, symbols: SymbolTable, swap: bool = False
) -> IRVariable:
    ir_args = ir.args[::-1] if swap else ir.args
    arg_0 = _convert_ir_basicblock(ctx, ir_args[0], symbols)
    arg_1 = _convert_ir_basicblock(ctx, ir_args[1], symbols)
    args = [arg_1, arg_0]

    ret = ctx.get_next_variable()

    inst = IRInstruction(str(ir.value), args, ret)
    ctx.get_basic_block().append_instruction(inst)
    return ret


def _append_jmp(ctx: IRFunction, label: IRLabel) -> None:
    inst = IRInstruction("jmp", [label])
    ctx.get_basic_block().append_instruction(inst)

    label = ctx.get_next_label()
    bb = IRBasicBlock(label, ctx)
    ctx.append_basic_block(bb)


def _new_block(ctx: IRFunction) -> IRBasicBlock:
    bb = IRBasicBlock(ctx.get_next_label(), ctx)
    bb = ctx.append_basic_block(bb)
    return bb


def _handle_self_call(ctx: IRFunction, ir: IRnode, symbols: SymbolTable) -> None:
    args_ir = ir.passthrough_metadata["args_ir"]
    goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
    target_label = goto_ir.args[0].value  # goto
    ret_values = [IRLabel(target_label)]
    for arg in args_ir:
        if arg.value != "with":
            ret = _convert_ir_basicblock(ctx, arg, symbols)
            new_var = ctx.append_instruction("calldataload", [ret])
            ret_values.append(new_var)
        else:
            ret = _convert_ir_basicblock(ctx, arg, symbols)
            ret_values.append(ret)

    return ctx.append_instruction("invoke", ret_values)


def _handle_internal_func(
    ctx: IRFunction, ir: IRnode, func_t: ContractFunctionT, symbols: SymbolTable
) -> IRnode:
    bb = IRBasicBlock(IRLabel(ir.args[0].args[0].value, True), ctx)
    bb = ctx.append_basic_block(bb)

    old_ir_mempos = 0
    old_ir_mempos += 64

    for _ in func_t.arguments:
        new_var = ctx.get_next_variable()

        alloca_inst = IRInstruction("alloca", [], new_var)
        bb.append_instruction(alloca_inst)
        symbols[f"&{old_ir_mempos}"] = new_var
        old_ir_mempos += 32

    return ir.args[0].args[2]


def _convert_ir_simple_node(
    ctx: IRFunction,
    ir: IRnode,
    symbols: SymbolTable,
) -> IRVariable:
    args = [_convert_ir_basicblock(ctx, arg, symbols) for arg in ir.args]
    return ctx.append_instruction(ir.value, args)


_break_target: IRBasicBlock = None
_continue_target: IRBasicBlock = None


def _convert_ir_basicblock(
    ctx: IRFunction,
    ir: IRnode,
    symbols: SymbolTable,
) -> Optional[IRVariable]:
    global _break_target, _continue_target
    # symbols = symbols.copy()

    if ir.value in BINARY_IR_INSTRUCTIONS:
        return _convert_binary_op(ctx, ir, symbols, ir.value in ["sha3", "sha3_64"])

    elif ir.value in MAPPED_IR_INSTRUCTIONS.keys():
        ir.value = MAPPED_IR_INSTRUCTIONS[ir.value]
        new_var = _convert_binary_op(ctx, ir, symbols)
        return ctx.append_instruction("iszero", [new_var])

    elif ir.value in ["iszero", "ceil32", "calldataload"]:
        return _convert_ir_simple_node(ctx, ir, symbols)

    elif ir.value in ["timestamp", "caller", "selfbalance", "calldatasize", "callvalue"]:
        return ctx.append_instruction(ir.value, [])

    elif ir.value in ["pass", "stop", "return"]:
        pass

    elif ir.value == "deploy":
        _convert_ir_basicblock(ctx, ir.args[1], symbols)
    elif ir.value == "seq":
        if ir.is_self_call:
            return _handle_self_call(ctx, ir, symbols)
        elif ir.passthrough_metadata.get("func_t", None) is not None:
            func_t = ir.passthrough_metadata["func_t"]
            ir = _handle_internal_func(ctx, ir, func_t, symbols)
            # fallthrough

        ret = None
        for ir_node in ir.args:  # NOTE: skip the last one
            ret = _convert_ir_basicblock(ctx, ir_node, symbols)

        return ret
    elif ir.value == "call":  # external call
        gas = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        address = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        value = _convert_ir_basicblock(ctx, ir.args[2], symbols)
        argsOffset = _convert_ir_basicblock(ctx, ir.args[3], symbols)
        argsSize = _convert_ir_basicblock(ctx, ir.args[4], symbols)
        retOffset = _convert_ir_basicblock(ctx, ir.args[5], symbols)
        retSize = _convert_ir_basicblock(ctx, ir.args[6], symbols)

        if argsOffset.is_literal:
            addr = argsOffset.value - 32 + 4
            argsOffsetVar = symbols.get(f"&{addr}", argsOffset.value)
            argsOffsetVar.mem_type = IRVariable.MemType.MEMORY
            argsOffsetVar.mem_addr = addr
            argsOffsetOp = IROperand(argsOffsetVar, True, 32 - 4)

        retVar = ctx.get_next_variable(IRVariable.MemType.MEMORY, retOffset.value)
        symbols[f"&{retOffset.value}"] = retVar

        inst = IRInstruction(
            "call", [gas, address, value, argsOffsetOp, argsSize, retOffset, retSize][::-1], retVar
        )
        ctx.get_basic_block().append_instruction(inst)
        return retVar
    elif ir.value == "if":
        cond = ir.args[0]
        current_bb = ctx.get_basic_block()

        # convert the condition
        cont_ret = _convert_ir_basicblock(ctx, cond, symbols)

        else_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(else_block)

        # convert "else"
        if len(ir.args) == 3:
            _convert_ir_basicblock(ctx, ir.args[2], symbols)
        after_else_syms = symbols.copy()

        # convert "then"
        then_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(then_block)

        _convert_ir_basicblock(ctx, ir.args[1], symbols)

        inst = IRInstruction("jnz", [cont_ret, then_block.label, else_block.label])
        current_bb.append_instruction(inst)

        after_then_syms = symbols.copy()

        # exit bb
        exit_label = ctx.get_next_label()
        bb = IRBasicBlock(exit_label, ctx)
        bb = ctx.append_basic_block(bb)

        # _emit_selects(ctx, after_then_syms, after_else_syms, then_block, else_block, bb)

        for sym, val in _get_symbols_common(after_then_syms, after_else_syms).items():
            ret = ctx.get_next_variable()
            symbols[sym] = ret
            bb.append_instruction(
                IRInstruction("select", [then_block.label, val[0], else_block.label, val[1]], ret)
            )

        if else_block.is_terminated is False:
            exit_inst = IRInstruction("jmp", [bb.label])
            else_block.append_instruction(exit_inst)

        if then_block.is_terminated is False:
            exit_inst = IRInstruction("jmp", [bb.label])
            then_block.append_instruction(exit_inst)

    elif ir.value == "with":
        ret = _convert_ir_basicblock(ctx, ir.args[1], symbols)  # initialization

        sym = ir.args[0]
        if ret.is_literal:
            new_var = ctx.append_instruction("store", [ret])
            symbols[sym.value] = new_var
        else:
            symbols[sym.value] = ret

        return _convert_ir_basicblock(ctx, ir.args[2], symbols)  # body
    elif ir.value == "goto":
        return _append_jmp(ctx, IRLabel(ir.args[0].value))
    elif ir.value == "jump":
        arg_1 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        inst = IRInstruction("jmp", [arg_1])
        ctx.get_basic_block().append_instruction(inst)
        _new_block(ctx)
    elif ir.value == "set":
        sym = ir.args[0]
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        new_var = ctx.append_instruction("store", [arg_1])
        symbols[sym.value] = new_var

    elif ir.value == "calldatacopy":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols)

        new_var = ctx.append_instruction("calldatacopy", [arg_1, size])

        symbols[f"&{arg_0.value}"] = new_var
        return new_var
    elif ir.value == "codecopy":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols)

        new_var = ctx.append_instruction("codecopy", [arg_1, size])

        symbols[f"&{arg_0.value}"] = new_var
    elif ir.value == "symbol":
        return IRLabel(ir.args[0].value)
    elif ir.value == "data":
        pass
    elif ir.value == "assert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        current_bb = ctx.get_basic_block()
        inst = IRInstruction("assert", [arg_0])
        current_bb.append_instruction(inst)
    elif ir.value == "label":
        label = IRLabel(ir.args[0].value, True)
        if ctx.get_basic_block().is_terminated is False:
            inst = IRInstruction("jmp", [label])
            ctx.get_basic_block().append_instruction(inst)
        bb = IRBasicBlock(label, ctx)
        ctx.append_basic_block(bb)
        _convert_ir_basicblock(ctx, ir.args[2], symbols)
    elif ir.value == "exit_to":
        if len(ir.args) == 1:
            inst = IRInstruction("ret", [])
            ctx.get_basic_block().append_instruction(inst)
        elif len(ir.args) >= 2:
            ret_var = ir.args[1]
            if ret_var.value == "return_pc":
                inst = IRInstruction("ret", [symbols["return_buffer"]])
                ctx.get_basic_block().append_instruction(inst)
                return None
            # else:
            #     new_var = ctx.get_next_variable()
            #     symbols[f"&{ret_var.value}"] = new_var

            last_ir = None
            for arg in ir.args[2:]:
                last_ir = _convert_ir_basicblock(ctx, arg, symbols)

            ret_ir = _convert_ir_basicblock(ctx, ret_var, symbols)
            new_var = symbols.get(f"&{ret_ir.value}", ret_ir)
            new_var.mem_type = IRVariable.MemType.MEMORY
            new_var.mem_addr = ret_ir.value
            new_op = IROperand(new_var, True)
            inst = IRInstruction("return", [last_ir, new_op])
            ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "revert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        inst = IRInstruction("revert", [arg_0, arg_1])
        ctx.get_basic_block().append_instruction(inst)

    elif ir.value == "dload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        return ctx.append_instruction("calldataload", [arg_0])

    elif ir.value == "mload":
        sym = ir.args[0]
        if sym.is_literal:
            new_var = symbols.get(f"&{sym.value}", None)
            if new_var is None:
                new_var = ctx.get_next_variable()
                symbols[f"&{sym.value}"] = new_var
                v = _convert_ir_basicblock(ctx, sym, symbols)
                op = IROperand(v, True)
                inst = IRInstruction("store", [op], new_var)
                ctx.get_basic_block().append_instruction(inst)
            return new_var
        else:
            new_var = _convert_ir_basicblock(ctx, sym, symbols)
            return new_var

    elif ir.value == "mstore":
        sym_ir = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        sym = symbols.get(f"&{arg_1.value}", None)

        if sym_ir.is_literal:
            new_var = ctx.append_instruction("store", [arg_1])
            symbols[f"&{sym_ir.value}"] = new_var
            return new_var
        else:
            new_var = ctx.append_instruction("store", [arg_1])
            symbols[sym_ir.value] = new_var
            return new_var
    elif ir.value == "sload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        return ctx.append_instruction("sload", [arg_0])
    elif ir.value == "sstore":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        inst = IRInstruction("sstore", [arg_0, arg_1])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "unique_symbol":
        sym = ir.args[0]
        new_var = ctx.get_next_variable()
        symbols[f"&{sym.value}"] = new_var
        return new_var
    elif ir.value == "return_buffer":
        return IRLabel("return_buffer", True)
    elif ir.value == "repeat":
        #
        # repeat(sym, start, end, bound, body)
        # 1) entry block         ]
        # 2) init counter block  ] -> same block
        # 3) condition block (exit block, body block)
        # 4) body block
        # 5) increment block
        # 6) exit block
        # TODO: Add the extra bounds check after clarify
        sym = ir.args[0]
        start = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        end = _convert_ir_basicblock(ctx, ir.args[2], symbols)
        bound = _convert_ir_basicblock(ctx, ir.args[3], symbols)
        body = ir.args[4]

        entry_block = ctx.get_basic_block()
        cond_block = IRBasicBlock(ctx.get_next_label(), ctx)
        body_block = IRBasicBlock(ctx.get_next_label(), ctx)
        jump_up_block = IRBasicBlock(ctx.get_next_label(), ctx)
        increment_block = IRBasicBlock(ctx.get_next_label(), ctx)
        exit_block = IRBasicBlock(ctx.get_next_label(), ctx)

        counter_var = ctx.get_next_variable()
        counter_inc_var = ctx.get_next_variable()
        ret = ctx.get_next_variable()
        symbols[sym.value] = ret
        cond_block.append_instruction(
            IRInstruction(
                "select",
                [entry_block.label, counter_var, increment_block.label, counter_inc_var],
                ret,
            )
        )

        inst = IRInstruction("store", [start], counter_var)
        ctx.get_basic_block().append_instruction(inst)
        symbols[sym.value] = counter_var
        inst = IRInstruction("jmp", [cond_block.label])
        ctx.get_basic_block().append_instruction(inst)

        cont_ret = ctx.get_next_variable()
        inst = IRInstruction("xor", [ret, end], cont_ret)
        cond_block.append_instruction(inst)
        ctx.append_basic_block(cond_block)

        ctx.append_basic_block(body_block)
        old_targets = _break_target, _continue_target
        _break_target, _continue_target = exit_block, increment_block
        _convert_ir_basicblock(ctx, body, symbols)
        _break_target, _continue_target = old_targets
        body_end = ctx.get_basic_block()
        if body_end.is_terminal() is False:
            body_end.append_instruction(IRInstruction("jmp", [jump_up_block.label]))

        jump_cond = IRInstruction("jmp", [increment_block.label])
        jump_up_block.append_instruction(jump_cond)
        ctx.append_basic_block(jump_up_block)

        increment_block.append_instruction(
            IRInstruction("add", [counter_var, IRLiteral(1)], counter_inc_var)
        )
        increment_block.append_instruction(IRInstruction("jmp", [cond_block.label]))
        ctx.append_basic_block(increment_block)

        ctx.append_basic_block(exit_block)

        inst = IRInstruction("jnz", [cont_ret, exit_block.label, body_block.label])
        cond_block.append_instruction(inst)
    elif ir.value == "break":
        assert _break_target is not None, "Break with no break target"
        inst = IRInstruction("jmp", [_break_target.label])
        ctx.get_basic_block().append_instruction(inst)
        ctx.append_basic_block(IRBasicBlock(ctx.get_next_label(), ctx))
    elif ir.value == "continue":
        pass
        assert _continue_target is not None, "Continue with no contrinue target"
        inst = IRInstruction("jmp", [_continue_target.label])
        ctx.get_basic_block().append_instruction(inst)
        ctx.append_basic_block(IRBasicBlock(ctx.get_next_label(), ctx))
    elif ir.value == "gas":
        return ctx.append_instruction("gas", [])
    elif ir.value == "returndatasize":
        return ctx.append_instruction("returndatasize", [])
    elif ir.value == "returndatacopy":
        assert len(ir.args) == 3, "returndatacopy with wrong number of arguments"
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols)

        new_var = ctx.append_instruction("returndatacopy", [arg_1, size])

        symbols[f"&{arg_0.value}"] = new_var
        return new_var
    elif isinstance(ir.value, str) and ir.value.startswith("log"):
        # count = int(ir.value[3:])
        args = [_convert_ir_basicblock(ctx, arg, symbols) for arg in ir.args]
        inst = IRInstruction(ir.value, args)
        ctx.get_basic_block().append_instruction(inst)
    elif isinstance(ir.value, str) and ir.value.upper() in get_opcodes():
        _convert_ir_opcode(ctx, ir, symbols)
    elif isinstance(ir.value, str) and ir.value in symbols:
        return symbols[ir.value]
    elif ir.is_literal:
        return IRLiteral(ir.value)
    else:
        raise Exception(f"Unknown IR node: {ir}")

    return None


def _convert_ir_opcode(ctx: IRFunction, ir: IRnode, symbols: SymbolTable) -> None:
    opcode = str(ir.value).upper()
    for arg in ir.args:
        if isinstance(arg, IRnode):
            _convert_ir_basicblock(ctx, arg, symbols)
    instruction = IRInstruction(opcode, ir.args)
    ctx.get_basic_block().append_instruction(instruction)
