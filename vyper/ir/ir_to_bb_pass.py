from typing import Optional, Union

from vyper.codegen.dfg import generate_evm
from vyper.codegen.ir_basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IROperant
from vyper.codegen.ir_function import IRFunction
from vyper.codegen.ir_node import IRnode
from vyper.compiler.settings import OptimizationLevel
from vyper.evm.opcodes import get_opcodes
from vyper.semantics.types.function import ContractFunctionT

TERMINATOR_IR_INSTRUCTIONS = ["jmp", "jnz", "ret", "revert"]

SymbolTable = dict[str, IROperant]


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

    while _optimize_empty_basicblocks(global_function):
        pass

    _calculate_in_set(global_function)

    while global_function.remove_unreachable_blocks():
        pass

    if len(global_function.basic_blocks) == 0:
        return global_function

    while True:
        _calculate_liveness(global_function.basic_blocks[0], set())

        # Optimization pass: Remove unused variables
        if optimize is OptimizationLevel.NONE:
            break

        removed = _optimize_unused_variables(global_function)
        if len(removed) == 0:
            break

    return global_function


def _optimize_unused_variables(ctx: IRFunction) -> list[IRInstruction]:
    """
    Remove unused variables.
    """
    count = 0
    removeList = []
    for bb in ctx.basic_blocks:
        for i, inst in enumerate(bb.instructions[:-1]):
            if inst.opcode in ["call", "sload", "sstore"]:
                continue
            if inst.ret and inst.ret not in bb.instructions[i + 1].liveness:
                removeList.append(inst)
                count += 1

        bb.instructions = [inst for inst in bb.instructions if inst not in removeList]

    return removeList


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

        for inst in bb.instructions:
            if inst.opcode in ["jmp", "jnz", "call"]:
                ops = inst.get_label_operands()
                for op in ops:
                    ctx.get_basic_block(op.value).add_in(bb)

    # Fill in the "out" set for each basic block
    for bb in ctx.basic_blocks:
        for in_bb in bb.in_set:
            in_bb.add_out(bb)


def _calculate_liveness(bb: IRBasicBlock, liveness_visited: set) -> None:
    bb.out_vars = set()
    for out_bb in bb.out_set:
        _calculate_liveness(out_bb, liveness_visited)
        in_vars = out_bb.in_vars_for(bb)
        bb.out_vars = bb.out_vars.union(in_vars)

    if bb in liveness_visited:
        return
    liveness_visited.add(bb)
    bb.calculate_liveness()


def _convert_binary_op(
    ctx: IRFunction, ir: IRnode, symbols: SymbolTable, swap: bool = False
) -> str:
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


def _handle_self_call(ctx: IRFunction, ir: IRnode, symbols: SymbolTable) -> None:
    args_ir = ir.passthrough_metadata["args_ir"]
    goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
    target_label = goto_ir.args[0].value  # goto
    ret_values = [IRLabel(target_label)]
    for arg in args_ir:
        if arg.value != "with":
            ret = _convert_ir_basicblock(ctx, arg, symbols)
            new_var = ctx.get_next_variable()
            inst = IRInstruction("calldataload", [ret], new_var)
            ctx.get_basic_block().append_instruction(inst)
            ret_values.append(new_var)
        else:
            ret = _convert_ir_basicblock(ctx, arg, symbols)
            ret_values.append(ret)

    call_ret = ctx.get_next_variable()
    call_inst = IRInstruction("call", ret_values, call_ret)
    ctx.get_basic_block().append_instruction(call_inst)
    return call_ret


def _handle_internal_func(
    ctx: IRFunction, ir: IRnode, func_t: ContractFunctionT, symbols: SymbolTable
) -> IRnode:
    bb = IRBasicBlock(IRLabel(ir.args[0].args[0].value, True), ctx)
    bb = ctx.append_basic_block(bb)

    old_ir_mempos = 0
    old_ir_mempos += 64

    for arg in func_t.arguments:
        new_var = ctx.get_next_variable()

        alloca_inst = IRInstruction("alloca", [], new_var)
        bb.append_instruction(alloca_inst)
        symbols[f"&{old_ir_mempos}"] = new_var
        old_ir_mempos += 32

    return ir.args[0].args[2]


def _convert_ir_basicblock(
    ctx: IRFunction, ir: IRnode, symbols: SymbolTable
) -> Optional[Union[str, int]]:
    # symbols = symbols.copy()

    if ir.value == "deploy":
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
        args = []
        for arg in ir.args:
            args.append(_convert_ir_basicblock(ctx, arg, symbols))

        ret = ctx.get_next_variable()
        inst = IRInstruction("call", args, ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
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

        for sym, val in _get_symbols_common(after_then_syms, after_else_syms).items():
            ret = ctx.get_next_variable()
            symbols[sym] = ret
            bb.append_instruction(
                IRInstruction("select", [then_block.label, val[0], else_block.label, val[1]], ret)
            )

        exit_inst = IRInstruction("jmp", [bb.label])
        else_block.append_instruction(exit_inst)

    elif ir.value == "with":
        ret = _convert_ir_basicblock(ctx, ir.args[1], symbols)  # initialization

        sym = ir.args[0]
        if ret.is_literal:
            new_var = ctx.get_next_variable()
            inst = IRInstruction("load", [ret], new_var)
            ctx.get_basic_block().append_instruction(inst)
            symbols[sym.value] = new_var
        else:
            symbols[sym.value] = ret

        return _convert_ir_basicblock(ctx, ir.args[2], symbols)  # body
    elif ir.value in [
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
    ]:
        return _convert_binary_op(ctx, ir, symbols, ir.value in ["sha3", "sha3_64"])
    elif ir.value == "le":
        ir.value = "gt"
        return _convert_binary_op(ctx, ir, symbols, False)  # TODO: check if this is correct order
    elif ir.value == "sle":
        ir.value = "sgt"
        return _convert_binary_op(ctx, ir, symbols, False)  # TODO: check if this is correct order
    elif ir.value == "ge":
        ir.value = "lt"
        return _convert_binary_op(ctx, ir, symbols, False)  # TODO: check if this is correct order
    elif ir.value == "sge":
        ir.value = "slt"
        return _convert_binary_op(ctx, ir, symbols, False)  # TODO: check if this is correct order
    elif ir.value == "iszero":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        args = [arg_0]

        ret = ctx.get_next_variable()

        inst = IRInstruction("iszero", args, ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "goto":
        return _append_jmp(ctx, IRLabel(ir.args[0].value))
    elif ir.value == "ceil32":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        new_var = ctx.get_next_variable()
        inst = IRInstruction("ceil32", [arg_0], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
    elif ir.value == "set":
        sym = ir.args[0]
        new_var = ctx.get_next_variable()
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        inst = IRInstruction("load", [arg_1], new_var)
        ctx.get_basic_block().append_instruction(inst)
        symbols[sym.value] = new_var
    elif ir.value == "calldatasize":
        ret = ctx.get_next_variable()
        inst = IRInstruction("calldatasize", [], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "calldataload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        ret = ctx.get_next_variable()
        inst = IRInstruction("calldataload", [arg_0], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "callvalue":
        ret = ctx.get_next_variable()
        inst = IRInstruction("callvalue", [], ret)
        ctx.get_basic_block().append_instruction(inst)
        return ret
    elif ir.value == "calldatacopy":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols)
        # orig_sym = symbols.get(f"&{arg_0.value}", None)
        # assert orig_sym is None, "calldatacopy should not have a symbol"
        new_var = ctx.get_next_variable()
        symbols[f"&{arg_0.value}"] = new_var
        inst = IRInstruction("calldatacopy", [arg_1, size], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
    elif ir.value == "assert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        current_bb = ctx.get_basic_block()

        new_var = ctx.get_next_variable()
        inst = IRInstruction("iszero", [arg_0], new_var)
        current_bb.append_instruction(inst)

        exit_label = ctx.get_next_label()
        bb = IRBasicBlock(exit_label, ctx)
        bb = ctx.append_basic_block(bb)

        inst = IRInstruction("jnz", [new_var, IRLabel("__revert"), exit_label])
        current_bb.append_instruction(inst)

    elif ir.value == "label":
        bb = IRBasicBlock(IRLabel(ir.args[0].value, True), ctx)
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
            inst = IRInstruction("ret", [ret_ir, last_ir])
            ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "revert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)
        inst = IRInstruction("revert", [arg_0, arg_1])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "timestamp":
        new_var = ctx.get_next_variable()
        inst = IRInstruction("timestamp", [], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
    elif ir.value == "caller":
        new_var = ctx.get_next_variable()
        inst = IRInstruction("caller", [], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
    elif ir.value == "dload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        new_var = ctx.get_next_variable()
        inst = IRInstruction("calldataload", [arg_0], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
    elif ir.value == "pass":
        pass
    elif ir.value == "stop":
        pass
    elif ir.value == "return":
        pass
    elif ir.value == "selfbalance":
        new_var = ctx.get_next_variable()
        inst = IRInstruction("selfbalance", [], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
    elif ir.value == "mload":
        sym = ir.args[0]
        if sym.is_literal:
            new_var = symbols.get(f"&{sym.value}", None)
            if new_var is None:
                new_var = ctx.get_next_variable()
                symbols[f"&{sym.value}"] = new_var
            return new_var
        else:
            new_var = _convert_ir_basicblock(ctx, sym, symbols)
            return new_var

    elif ir.value == "mstore":
        sym_ir = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols)

        if sym_ir.is_literal:
            sym = symbols.get(f"&{arg_1.value}", None)
            if sym is None:
                symbols[f"&{sym_ir.value}"] = arg_1
                return arg_1
            else:
                new_var = ctx.get_next_variable()
                inst = IRInstruction("load", [sym], new_var)
                ctx.get_basic_block().append_instruction(inst)
                symbols[f"&{sym_ir.value}"] = new_var
                return new_var
        else:
            new_var = ctx.get_next_variable()
            inst = IRInstruction("load", [arg_1], new_var)
            ctx.get_basic_block().append_instruction(inst)
            symbols[sym_ir.value] = new_var
            return new_var
    elif ir.value == "sload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols)
        new_var = ctx.get_next_variable()
        inst = IRInstruction("sload", [arg_0], new_var)
        ctx.get_basic_block().append_instruction(inst)
        return new_var
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
