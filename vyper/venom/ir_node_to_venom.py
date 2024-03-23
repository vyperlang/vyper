import functools
import re
from typing import Optional

from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import get_opcodes
from vyper.utils import MemoryPositions
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction

# Instructions that are mapped to their inverse
INVERSE_MAPPED_IR_INSTRUCTIONS = {"ne": "eq", "le": "gt", "sle": "sgt", "ge": "lt", "sge": "slt"}

# Instructions that have a direct EVM opcode equivalent and can
# be passed through to the EVM assembly without special handling
PASS_THROUGH_INSTRUCTIONS = frozenset(
    [
        # binary instructions
        "eq",
        "gt",
        "lt",
        "slt",
        "sgt",
        "shr",
        "shl",
        "sar",
        "or",
        "xor",
        "and",
        "add",
        "sub",
        "mul",
        "div",
        "smul",
        "sdiv",
        "mod",
        "smod",
        "exp",
        "sha3",
        "sha3_64",
        "signextend",
        "chainid",
        "basefee",
        "timestamp",
        "blockhash",
        "caller",
        "selfbalance",
        "calldatasize",
        "callvalue",
        "address",
        "origin",
        "codesize",
        "gas",
        "gasprice",
        "gaslimit",
        "returndatasize",
        "iload",
        "sload",
        "tload",
        "coinbase",
        "number",
        "prevrandao",
        "difficulty",
        "iszero",
        "not",
        "calldataload",
        "extcodesize",
        "extcodehash",
        "balance",
        "msize",
        "basefee",
        "invalid",
        "stop",
        "selfdestruct",
        "assert",
        "assert_unreachable",
        "exit",
        "calldatacopy",
        "mcopy",
        "extcodecopy",
        "codecopy",
        "returndatacopy",
        "revert",
        "istore",
        "sstore",
        "tstore",
        "create",
        "create2",
        "addmod",
        "mulmod",
        "call",
        "delegatecall",
        "staticcall",
    ]
)

NOOP_INSTRUCTIONS = frozenset(["pass", "cleanup_repeat", "var_list", "unique_symbol"])

SymbolTable = dict[str, Optional[IROperand]]


# convert IRnode directly to venom
def ir_node_to_venom(ir: IRnode) -> IRFunction:
    ctx = IRFunction()
    _convert_ir_bb(ctx, ir, {})

    # Patch up basic blocks. Connect unterminated blocks to the next with
    # a jump. terminate final basic block with STOP.
    for i, bb in enumerate(ctx.basic_blocks):
        if not bb.is_terminated:
            if len(ctx.basic_blocks) - 1 > i:
                # TODO: revisit this. When contructor calls internal functions they
                # are linked to the last ctor block. Should separate them before this
                # so we don't have to handle this here
                if ctx.basic_blocks[i + 1].label.value.startswith("internal"):
                    bb.append_instruction("stop")
                else:
                    bb.append_instruction("jmp", ctx.basic_blocks[i + 1].label)
            else:
                bb.append_instruction("exit")

    return ctx


def _append_jmp(ctx: IRFunction, label: IRLabel) -> None:
    bb = ctx.get_basic_block()
    if bb.is_terminated:
        bb = IRBasicBlock(ctx.get_next_label("jmp_target"), ctx)
        ctx.append_basic_block(bb)

    bb.append_instruction("jmp", label)


def _new_block(ctx: IRFunction) -> IRBasicBlock:
    bb = IRBasicBlock(ctx.get_next_label(), ctx)
    bb = ctx.append_basic_block(bb)
    return bb


def _append_return_args(ctx: IRFunction, ofst: int = 0, size: int = 0):
    bb = ctx.get_basic_block()
    if bb.is_terminated:
        bb = IRBasicBlock(ctx.get_next_label("exit_to"), ctx)
        ctx.append_basic_block(bb)
    ret_ofst = IRVariable("ret_ofst")
    ret_size = IRVariable("ret_size")
    bb.append_instruction("store", ofst, ret=ret_ofst)
    bb.append_instruction("store", size, ret=ret_size)


def _handle_self_call(ctx: IRFunction, ir: IRnode, symbols: SymbolTable) -> Optional[IRVariable]:
    setup_ir = ir.args[1]
    goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
    target_label = goto_ir.args[0].value  # goto
    return_buf_ir = goto_ir.args[1]  # return buffer
    ret_args: list[IROperand] = [IRLabel(target_label)]  # type: ignore

    if setup_ir != goto_ir:
        _convert_ir_bb(ctx, setup_ir, symbols)

    return_buf = _convert_ir_bb(ctx, return_buf_ir, symbols)

    bb = ctx.get_basic_block()
    if len(goto_ir.args) > 2:
        ret_args.append(return_buf)  # type: ignore

    bb.append_invoke_instruction(ret_args, returns=False)  # type: ignore

    return return_buf


def _handle_internal_func(
    ctx: IRFunction, ir: IRnode, does_return_data: bool, symbols: SymbolTable
):
    bb = IRBasicBlock(IRLabel(ir.args[0].args[0].value, True), ctx)  # type: ignore
    bb = ctx.append_basic_block(bb)

    # return buffer
    if does_return_data:
        symbols["return_buffer"] = bb.append_instruction("param")
        bb.instructions[-1].annotation = "return_buffer"

    # return address
    symbols["return_pc"] = bb.append_instruction("param")
    bb.instructions[-1].annotation = "return_pc"

    _convert_ir_bb(ctx, ir.args[0].args[2], symbols)


def _convert_ir_simple_node(
    ctx: IRFunction, ir: IRnode, symbols: SymbolTable
) -> Optional[IRVariable]:
    # execute in order
    args = _convert_ir_bb_list(ctx, ir.args, symbols)
    # reverse output variables for stack
    args.reverse()
    return ctx.get_basic_block().append_instruction(ir.value, *args)  # type: ignore


_break_target: Optional[IRBasicBlock] = None
_continue_target: Optional[IRBasicBlock] = None


def _convert_ir_bb_list(ctx, ir, symbols):
    ret = []
    for ir_node in ir:
        venom = _convert_ir_bb(ctx, ir_node, symbols)
        ret.append(venom)
    return ret


current_func = None
var_list: list[str] = []


def pop_source_on_return(func):
    @functools.wraps(func)
    def pop_source(*args, **kwargs):
        ctx = args[0]
        ret = func(*args, **kwargs)
        ctx.pop_source()
        return ret

    return pop_source


@pop_source_on_return
def _convert_ir_bb(ctx, ir, symbols):
    assert isinstance(ir, IRnode), ir
    global _break_target, _continue_target, current_func, var_list

    ctx.push_source(ir)

    if ir.value in INVERSE_MAPPED_IR_INSTRUCTIONS:
        org_value = ir.value
        ir.value = INVERSE_MAPPED_IR_INSTRUCTIONS[ir.value]
        new_var = _convert_ir_simple_node(ctx, ir, symbols)
        ir.value = org_value
        return ctx.get_basic_block().append_instruction("iszero", new_var)
    elif ir.value in PASS_THROUGH_INSTRUCTIONS:
        return _convert_ir_simple_node(ctx, ir, symbols)
    elif ir.value == "return":
        ctx.get_basic_block().append_instruction(
            "return", IRVariable("ret_size"), IRVariable("ret_ofst")
        )
    elif ir.value == "deploy":
        ctx.ctor_mem_size = ir.args[0].value
        ctx.immutables_len = ir.args[2].value
        return None
    elif ir.value == "seq":
        if len(ir.args) == 0:
            return None
        if ir.is_self_call:
            return _handle_self_call(ctx, ir, symbols)
        elif ir.args[0].value == "label":
            current_func = ir.args[0].args[0].value
            is_external = current_func.startswith("external")
            is_internal = current_func.startswith("internal")
            if is_internal or len(re.findall(r"external.*__init__\(.*_deploy", current_func)) > 0:
                # Internal definition
                var_list = ir.args[0].args[1]
                does_return_data = IRnode.from_list(["return_buffer"]) in var_list.args
                symbols = {}
                _handle_internal_func(ctx, ir, does_return_data, symbols)
                for ir_node in ir.args[1:]:
                    ret = _convert_ir_bb(ctx, ir_node, symbols)

                return ret
            elif is_external:
                ret = _convert_ir_bb(ctx, ir.args[0], symbols)
                _append_return_args(ctx)
        else:
            bb = ctx.get_basic_block()
            if bb.is_terminated:
                bb = IRBasicBlock(ctx.get_next_label("seq"), ctx)
                ctx.append_basic_block(bb)
            ret = _convert_ir_bb(ctx, ir.args[0], symbols)

        for ir_node in ir.args[1:]:
            ret = _convert_ir_bb(ctx, ir_node, symbols)

        return ret
    elif ir.value == "if":
        cond = ir.args[0]

        # convert the condition
        cont_ret = _convert_ir_bb(ctx, cond, symbols)
        cond_block = ctx.get_basic_block()

        cond_symbols = symbols.copy()

        else_block = IRBasicBlock(ctx.get_next_label("else"), ctx)
        ctx.append_basic_block(else_block)

        # convert "else"
        else_ret_val = None
        if len(ir.args) == 3:
            else_ret_val = _convert_ir_bb(ctx, ir.args[2], cond_symbols)
            if isinstance(else_ret_val, IRLiteral):
                assert isinstance(else_ret_val.value, int)  # help mypy
                else_ret_val = ctx.get_basic_block().append_instruction("store", else_ret_val)

        else_block_finish = ctx.get_basic_block()

        # convert "then"
        cond_symbols = symbols.copy()

        then_block = IRBasicBlock(ctx.get_next_label("then"), ctx)
        ctx.append_basic_block(then_block)

        then_ret_val = _convert_ir_bb(ctx, ir.args[1], cond_symbols)
        if isinstance(then_ret_val, IRLiteral):
            then_ret_val = ctx.get_basic_block().append_instruction("store", then_ret_val)

        cond_block.append_instruction("jnz", cont_ret, then_block.label, else_block.label)

        then_block_finish = ctx.get_basic_block()

        # exit bb
        exit_bb = IRBasicBlock(ctx.get_next_label("if_exit"), ctx)
        exit_bb = ctx.append_basic_block(exit_bb)

        if_ret = ctx.get_next_variable()
        if then_ret_val is not None and else_ret_val is not None:
            then_block_finish.append_instruction("store", then_ret_val, ret=if_ret)
            else_block_finish.append_instruction("store", else_ret_val, ret=if_ret)

        if not else_block_finish.is_terminated:
            else_block_finish.append_instruction("jmp", exit_bb.label)

        if not then_block_finish.is_terminated:
            then_block_finish.append_instruction("jmp", exit_bb.label)

        return if_ret

    elif ir.value == "with":
        ret = _convert_ir_bb(ctx, ir.args[1], symbols)  # initialization

        ret = ctx.get_basic_block().append_instruction("store", ret)

        # Handle with nesting with same symbol
        with_symbols = symbols.copy()

        sym = ir.args[0]
        with_symbols[sym.value] = ret

        return _convert_ir_bb(ctx, ir.args[2], with_symbols)  # body
    elif ir.value == "goto":
        _append_jmp(ctx, IRLabel(ir.args[0].value))
    elif ir.value == "djump":
        args = [_convert_ir_bb(ctx, ir.args[0], symbols)]
        for target in ir.args[1:]:
            args.append(IRLabel(target.value))
        ctx.get_basic_block().append_instruction("djmp", *args)
        _new_block(ctx)
    elif ir.value == "set":
        sym = ir.args[0]
        arg_1 = _convert_ir_bb(ctx, ir.args[1], symbols)
        ctx.get_basic_block().append_instruction("store", arg_1, ret=symbols[sym.value])
    elif ir.value == "symbol":
        return IRLabel(ir.args[0].value, True)
    elif ir.value == "data":
        label = IRLabel(ir.args[0].value)
        ctx.append_data("dbname", [label])
        for c in ir.args[1:]:
            if isinstance(c, int):
                assert 0 <= c <= 255, "data with invalid size"
                ctx.append_data("db", [c])  # type: ignore
            elif isinstance(c.value, bytes):
                ctx.append_data("db", [c.value])  # type: ignore
            elif isinstance(c, IRnode):
                data = _convert_ir_bb(ctx, c, symbols)
                ctx.append_data("db", [data])  # type: ignore
    elif ir.value == "label":
        label = IRLabel(ir.args[0].value, True)
        bb = ctx.get_basic_block()
        if not bb.is_terminated:
            bb.append_instruction("jmp", label)
        bb = IRBasicBlock(label, ctx)
        ctx.append_basic_block(bb)
        code = ir.args[2]
        if code.value == "pass":
            bb.append_instruction("exit")
        else:
            _convert_ir_bb(ctx, code, symbols)
    elif ir.value == "exit_to":
        args = _convert_ir_bb_list(ctx, ir.args[1:], symbols)
        var_list = args
        _append_return_args(ctx, *var_list)
        bb = ctx.get_basic_block()
        if bb.is_terminated:
            bb = IRBasicBlock(ctx.get_next_label("exit_to"), ctx)
            ctx.append_basic_block(bb)
        bb = ctx.get_basic_block()

        label = IRLabel(ir.args[0].value)
        if label.value == "return_pc":
            label = symbols.get("return_pc")
            bb.append_instruction("ret", label)
        else:
            bb.append_instruction("jmp", label)

    elif ir.value == "dload":
        arg_0 = _convert_ir_bb(ctx, ir.args[0], symbols)
        bb = ctx.get_basic_block()
        src = bb.append_instruction("add", arg_0, IRLabel("code_end"))

        bb.append_instruction("dloadbytes", 32, src, MemoryPositions.FREE_VAR_SPACE)
        return bb.append_instruction("mload", MemoryPositions.FREE_VAR_SPACE)

    elif ir.value == "dloadbytes":
        dst, src_offset, len_ = _convert_ir_bb_list(ctx, ir.args, symbols)

        bb = ctx.get_basic_block()
        src = bb.append_instruction("add", src_offset, IRLabel("code_end"))
        bb.append_instruction("dloadbytes", len_, src, dst)
        return None

    elif ir.value == "mload":
        arg_0 = _convert_ir_bb(ctx, ir.args[0], symbols)
        bb = ctx.get_basic_block()
        if isinstance(arg_0, IRVariable):
            return bb.append_instruction("mload", arg_0)

        if isinstance(arg_0, IRLiteral):
            avar = symbols.get(f"%{arg_0.value}")
            if avar is not None:
                return bb.append_instruction("mload", avar)

        return bb.append_instruction("mload", arg_0)
    elif ir.value == "mstore":
        # some upstream code depends on reversed order of evaluation --
        # to fix upstream.
        arg_1, arg_0 = _convert_ir_bb_list(ctx, reversed(ir.args), symbols)

        if isinstance(arg_1, IRVariable):
            symbols[f"&{arg_0.value}"] = arg_1

        ctx.get_basic_block().append_instruction("mstore", arg_1, arg_0)
    elif ir.value == "ceil32":
        x = ir.args[0]
        expanded = IRnode.from_list(["and", ["add", x, 31], ["not", 31]])
        return _convert_ir_bb(ctx, expanded, symbols)
    elif ir.value == "select":
        cond, a, b = ir.args
        expanded = IRnode.from_list(
            [
                "with",
                "cond",
                cond,
                [
                    "with",
                    "a",
                    a,
                    ["with", "b", b, ["xor", "b", ["mul", "cond", ["xor", "a", "b"]]]],
                ],
            ]
        )
        return _convert_ir_bb(ctx, expanded, symbols)
    elif ir.value == "repeat":

        def emit_body_blocks():
            global _break_target, _continue_target
            old_targets = _break_target, _continue_target
            _break_target, _continue_target = exit_block, incr_block
            _convert_ir_bb(ctx, body, symbols.copy())
            _break_target, _continue_target = old_targets

        sym = ir.args[0]
        start, end, _ = _convert_ir_bb_list(ctx, ir.args[1:4], symbols)

        assert ir.args[3].is_literal, "repeat bound expected to be literal"

        bound = ir.args[3].value
        if (
            isinstance(end, IRLiteral)
            and isinstance(start, IRLiteral)
            and end.value + start.value <= bound
        ):
            bound = None

        body = ir.args[4]

        entry_block = IRBasicBlock(ctx.get_next_label("repeat"), ctx)
        cond_block = IRBasicBlock(ctx.get_next_label("condition"), ctx)
        body_block = IRBasicBlock(ctx.get_next_label("body"), ctx)
        incr_block = IRBasicBlock(ctx.get_next_label("incr"), ctx)
        exit_block = IRBasicBlock(ctx.get_next_label("exit"), ctx)

        bb = ctx.get_basic_block()
        bb.append_instruction("jmp", entry_block.label)
        ctx.append_basic_block(entry_block)

        counter_var = entry_block.append_instruction("store", start)
        symbols[sym.value] = counter_var
        end = entry_block.append_instruction("add", start, end)
        if bound:
            bound = entry_block.append_instruction("add", start, bound)
        entry_block.append_instruction("jmp", cond_block.label)

        xor_ret = cond_block.append_instruction("xor", counter_var, end)
        cont_ret = cond_block.append_instruction("iszero", xor_ret)
        ctx.append_basic_block(cond_block)

        ctx.append_basic_block(body_block)
        if bound:
            xor_ret = body_block.append_instruction("xor", counter_var, bound)
            body_block.append_instruction("assert", xor_ret)

        emit_body_blocks()
        body_end = ctx.get_basic_block()
        if body_end.is_terminated is False:
            body_end.append_instruction("jmp", incr_block.label)

        ctx.append_basic_block(incr_block)
        incr_block.insert_instruction(
            IRInstruction("add", [counter_var, IRLiteral(1)], counter_var)
        )
        incr_block.append_instruction("jmp", cond_block.label)

        ctx.append_basic_block(exit_block)

        cond_block.append_instruction("jnz", cont_ret, exit_block.label, body_block.label)
    elif ir.value == "break":
        assert _break_target is not None, "Break with no break target"
        ctx.get_basic_block().append_instruction("jmp", _break_target.label)
        ctx.append_basic_block(IRBasicBlock(ctx.get_next_label(), ctx))
    elif ir.value == "continue":
        assert _continue_target is not None, "Continue with no contrinue target"
        ctx.get_basic_block().append_instruction("jmp", _continue_target.label)
        ctx.append_basic_block(IRBasicBlock(ctx.get_next_label(), ctx))
    elif ir.value in NOOP_INSTRUCTIONS:
        pass
    elif isinstance(ir.value, str) and ir.value.startswith("log"):
        args = reversed(_convert_ir_bb_list(ctx, ir.args, symbols))
        topic_count = int(ir.value[3:])
        assert topic_count >= 0 and topic_count <= 4, "invalid topic count"
        ctx.get_basic_block().append_instruction("log", topic_count, *args)
    elif isinstance(ir.value, str) and ir.value.upper() in get_opcodes():
        _convert_ir_opcode(ctx, ir, symbols)
    elif isinstance(ir.value, str):
        if ir.value.startswith("$alloca") and ir.value not in symbols:
            alloca = ir.passthrough_metadata["alloca"]
            ptr = ctx.get_basic_block().append_instruction("alloca", alloca.offset, alloca.size)
            symbols[ir.value] = ptr
        return symbols[ir.value]
    elif ir.is_literal:
        return IRLiteral(ir.value)
    else:
        raise Exception(f"Unknown IR node: {ir}")

    return None


def _convert_ir_opcode(ctx: IRFunction, ir: IRnode, symbols: SymbolTable) -> None:
    opcode = ir.value.upper()  # type: ignore
    inst_args = []
    for arg in ir.args:
        if isinstance(arg, IRnode):
            inst_args.append(_convert_ir_bb(ctx, arg, symbols))
    ctx.get_basic_block().append_instruction(opcode, *inst_args)
