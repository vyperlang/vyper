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
from vyper.venom.context import IRContext
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
        "blobhash",
        "blobbasefee",
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
        "mload",
        "iload",
        "istore",
        "sload",
        "sstore",
        "tload",
        "tstore",
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
_global_symbols: SymbolTable = None  # type: ignore
MAIN_ENTRY_LABEL_NAME = "__main_entry"
_external_functions: dict[int, SymbolTable] = None  # type: ignore


# convert IRnode directly to venom
def ir_node_to_venom(ir: IRnode) -> IRContext:
    _ = ir.unique_symbols  # run unique symbols check

    global _global_symbols, _external_functions
    _global_symbols = {}
    _external_functions = {}

    ctx = IRContext()
    fn = ctx.create_function(MAIN_ENTRY_LABEL_NAME)

    _convert_ir_bb(fn, ir, {})

    ctx.chain_basic_blocks()

    return ctx


def _append_jmp(fn: IRFunction, label: IRLabel) -> None:
    bb = fn.get_basic_block()
    if bb.is_terminated:
        bb = IRBasicBlock(fn.ctx.get_next_label("jmp_target"), fn)
        fn.append_basic_block(bb)

    bb.append_instruction("jmp", label)


def _new_block(fn: IRFunction) -> None:
    bb = IRBasicBlock(fn.ctx.get_next_label(), fn)
    fn.append_basic_block(bb)


def _append_return_args(fn: IRFunction, ofst: int = 0, size: int = 0):
    bb = fn.get_basic_block()
    if bb.is_terminated:
        bb = IRBasicBlock(fn.ctx.get_next_label("exit_to"), fn)
        fn.append_basic_block(bb)
    ret_ofst = IRVariable("ret_ofst")
    ret_size = IRVariable("ret_size")
    bb.append_instruction("store", ofst, ret=ret_ofst)
    bb.append_instruction("store", size, ret=ret_size)


def _handle_self_call(fn: IRFunction, ir: IRnode, symbols: SymbolTable) -> Optional[IRVariable]:
    setup_ir = ir.args[1]
    goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
    target_label = goto_ir.args[0].value  # goto
    return_buf_ir = goto_ir.args[1]  # return buffer
    ret_args: list[IROperand] = [IRLabel(target_label)]  # type: ignore

    if setup_ir != goto_ir:
        _convert_ir_bb(fn, setup_ir, symbols)

    return_buf = _convert_ir_bb(fn, return_buf_ir, symbols)

    bb = fn.get_basic_block()
    if len(goto_ir.args) > 2:
        ret_args.append(return_buf)  # type: ignore

    bb.append_invoke_instruction(ret_args, returns=False)  # type: ignore

    return return_buf


def _handle_internal_func(
    fn: IRFunction, ir: IRnode, does_return_data: bool, symbols: SymbolTable
) -> IRFunction:
    fn = fn.ctx.create_function(ir.args[0].args[0].value)
    bb = fn.get_basic_block()

    # return buffer
    if does_return_data:
        symbols["return_buffer"] = bb.append_instruction("param")
        bb.instructions[-1].annotation = "return_buffer"

    # return address
    symbols["return_pc"] = bb.append_instruction("param")
    bb.instructions[-1].annotation = "return_pc"

    _convert_ir_bb(fn, ir.args[0].args[2], symbols)

    return fn


def _convert_ir_simple_node(
    fn: IRFunction, ir: IRnode, symbols: SymbolTable
) -> Optional[IRVariable]:
    # execute in order
    args = _convert_ir_bb_list(fn, ir.args, symbols)
    # reverse output variables for stack
    args.reverse()
    return fn.get_basic_block().append_instruction(ir.value, *args)  # type: ignore


_break_target: Optional[IRBasicBlock] = None
_continue_target: Optional[IRBasicBlock] = None


def _convert_ir_bb_list(fn, ir, symbols):
    ret = []
    for ir_node in ir:
        venom = _convert_ir_bb(fn, ir_node, symbols)
        ret.append(venom)
    return ret


def pop_source_on_return(func):
    @functools.wraps(func)
    def pop_source(*args, **kwargs):
        fn = args[0]
        ret = func(*args, **kwargs)
        fn.pop_source()
        return ret

    return pop_source


@pop_source_on_return
def _convert_ir_bb(fn, ir, symbols):
    assert isinstance(ir, IRnode), ir
    # TODO: refactor these to not be globals
    global _break_target, _continue_target, _global_symbols, _external_functions

    # keep a map from external functions to all possible entry points

    ctx = fn.ctx
    fn.push_source(ir)

    if ir.value in INVERSE_MAPPED_IR_INSTRUCTIONS:
        org_value = ir.value
        ir.value = INVERSE_MAPPED_IR_INSTRUCTIONS[ir.value]
        new_var = _convert_ir_simple_node(fn, ir, symbols)
        ir.value = org_value
        return fn.get_basic_block().append_instruction("iszero", new_var)
    elif ir.value in PASS_THROUGH_INSTRUCTIONS:
        return _convert_ir_simple_node(fn, ir, symbols)
    elif ir.value == "return":
        fn.get_basic_block().append_instruction(
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
            return _handle_self_call(fn, ir, symbols)
        elif ir.args[0].value == "label":
            current_func = ir.args[0].args[0].value
            is_external = current_func.startswith("external")
            is_internal = current_func.startswith("internal")
            if is_internal or len(re.findall(r"external.*__init__\(.*_deploy", current_func)) > 0:
                # Internal definition
                var_list = ir.args[0].args[1]
                does_return_data = IRnode.from_list(["return_buffer"]) in var_list.args
                _global_symbols = {}
                symbols = {}
                new_fn = _handle_internal_func(fn, ir, does_return_data, symbols)
                for ir_node in ir.args[1:]:
                    ret = _convert_ir_bb(new_fn, ir_node, symbols)

                return ret
            elif is_external:
                ret = _convert_ir_bb(fn, ir.args[0], symbols)
                _append_return_args(fn)
        else:
            bb = fn.get_basic_block()
            if bb.is_terminated:
                bb = IRBasicBlock(ctx.get_next_label("seq"), fn)
                fn.append_basic_block(bb)
            ret = _convert_ir_bb(fn, ir.args[0], symbols)

        for ir_node in ir.args[1:]:
            ret = _convert_ir_bb(fn, ir_node, symbols)

        return ret
    elif ir.value == "if":
        cond = ir.args[0]

        # convert the condition
        cont_ret = _convert_ir_bb(fn, cond, symbols)
        cond_block = fn.get_basic_block()

        saved_global_symbols = _global_symbols.copy()

        then_block = IRBasicBlock(ctx.get_next_label("then"), fn)
        else_block = IRBasicBlock(ctx.get_next_label("else"), fn)

        # convert "then"
        cond_symbols = symbols.copy()
        fn.append_basic_block(then_block)
        then_ret_val = _convert_ir_bb(fn, ir.args[1], cond_symbols)
        if isinstance(then_ret_val, IRLiteral):
            then_ret_val = fn.get_basic_block().append_instruction("store", then_ret_val)

        then_block_finish = fn.get_basic_block()

        # convert "else"
        cond_symbols = symbols.copy()
        _global_symbols = saved_global_symbols.copy()
        fn.append_basic_block(else_block)
        else_ret_val = None
        if len(ir.args) == 3:
            else_ret_val = _convert_ir_bb(fn, ir.args[2], cond_symbols)
            if isinstance(else_ret_val, IRLiteral):
                assert isinstance(else_ret_val.value, int)  # help mypy
                else_ret_val = fn.get_basic_block().append_instruction("store", else_ret_val)

        else_block_finish = fn.get_basic_block()

        # finish the condition block
        cond_block.append_instruction("jnz", cont_ret, then_block.label, else_block.label)

        # exit bb
        exit_bb = IRBasicBlock(ctx.get_next_label("if_exit"), fn)
        fn.append_basic_block(exit_bb)

        if_ret = fn.get_next_variable()
        if then_ret_val is not None and else_ret_val is not None:
            then_block_finish.append_instruction("store", then_ret_val, ret=if_ret)
            else_block_finish.append_instruction("store", else_ret_val, ret=if_ret)

        if not else_block_finish.is_terminated:
            else_block_finish.append_instruction("jmp", exit_bb.label)

        if not then_block_finish.is_terminated:
            then_block_finish.append_instruction("jmp", exit_bb.label)

        _global_symbols = saved_global_symbols

        return if_ret

    elif ir.value == "with":
        ret = _convert_ir_bb(fn, ir.args[1], symbols)  # initialization

        ret = fn.get_basic_block().append_instruction("store", ret)

        sym = ir.args[0]
        with_symbols = symbols.copy()
        with_symbols[sym.value] = ret

        return _convert_ir_bb(fn, ir.args[2], with_symbols)  # body

    elif ir.value == "goto":
        _append_jmp(fn, IRLabel(ir.args[0].value))
    elif ir.value == "djump":
        args = [_convert_ir_bb(fn, ir.args[0], symbols)]
        for target in ir.args[1:]:
            args.append(IRLabel(target.value))
        fn.get_basic_block().append_instruction("djmp", *args)
        _new_block(fn)
    elif ir.value == "set":
        sym = ir.args[0]
        arg_1 = _convert_ir_bb(fn, ir.args[1], symbols)
        fn.get_basic_block().append_instruction("store", arg_1, ret=symbols[sym.value])
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
                data = _convert_ir_bb(fn, c, symbols)
                ctx.append_data("db", [data])  # type: ignore
    elif ir.value == "label":
        function_id_pattern = r"external (\d+)"
        function_name = ir.args[0].value
        m = re.match(function_id_pattern, function_name)
        if m is not None:
            function_id = m.group(1)
            _global_symbols = _external_functions.setdefault(function_id, {})

        label = IRLabel(ir.args[0].value, True)
        bb = fn.get_basic_block()
        if not bb.is_terminated:
            bb.append_instruction("jmp", label)
        bb = IRBasicBlock(label, fn)
        fn.append_basic_block(bb)
        code = ir.args[2]
        if code.value == "pass":
            bb.append_instruction("exit")
        else:
            _convert_ir_bb(fn, code, symbols)
    elif ir.value == "exit_to":
        args = _convert_ir_bb_list(fn, ir.args[1:], symbols)
        var_list = args
        _append_return_args(fn, *var_list)
        bb = fn.get_basic_block()
        if bb.is_terminated:
            bb = IRBasicBlock(ctx.get_next_label("exit_to"), fn)
            fn.append_basic_block(bb)
        bb = fn.get_basic_block()

        label = IRLabel(ir.args[0].value)
        if label.value == "return_pc":
            label = symbols.get("return_pc")
            bb.append_instruction("ret", label)
        else:
            bb.append_instruction("jmp", label)

    elif ir.value == "dload":
        arg_0 = _convert_ir_bb(fn, ir.args[0], symbols)
        bb = fn.get_basic_block()
        src = bb.append_instruction("add", arg_0, IRLabel("code_end"))

        bb.append_instruction("dloadbytes", 32, src, MemoryPositions.FREE_VAR_SPACE)
        return bb.append_instruction("mload", MemoryPositions.FREE_VAR_SPACE)

    elif ir.value == "dloadbytes":
        dst, src_offset, len_ = _convert_ir_bb_list(fn, ir.args, symbols)

        bb = fn.get_basic_block()
        src = bb.append_instruction("add", src_offset, IRLabel("code_end"))
        bb.append_instruction("dloadbytes", len_, src, dst)
        return None

    elif ir.value == "mstore":
        # some upstream code depends on reversed order of evaluation --
        # to fix upstream.
        val, ptr = _convert_ir_bb_list(fn, reversed(ir.args), symbols)

        return fn.get_basic_block().append_instruction("mstore", val, ptr)

    elif ir.value == "ceil32":
        x = ir.args[0]
        expanded = IRnode.from_list(["and", ["add", x, 31], ["not", 31]])
        return _convert_ir_bb(fn, expanded, symbols)
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
        return _convert_ir_bb(fn, expanded, symbols)
    elif ir.value == "repeat":

        def emit_body_blocks():
            global _break_target, _continue_target, _global_symbols
            old_targets = _break_target, _continue_target
            _break_target, _continue_target = exit_block, incr_block
            saved_global_symbols = _global_symbols.copy()
            _convert_ir_bb(fn, body, symbols.copy())
            _break_target, _continue_target = old_targets
            _global_symbols = saved_global_symbols

        sym = ir.args[0]
        start, end, _ = _convert_ir_bb_list(fn, ir.args[1:4], symbols)

        assert ir.args[3].is_literal, "repeat bound expected to be literal"
        bound = ir.args[3].value

        body = ir.args[4]

        entry_block = IRBasicBlock(ctx.get_next_label("repeat"), fn)
        cond_block = IRBasicBlock(ctx.get_next_label("condition"), fn)
        body_block = IRBasicBlock(ctx.get_next_label("body"), fn)
        incr_block = IRBasicBlock(ctx.get_next_label("incr"), fn)
        exit_block = IRBasicBlock(ctx.get_next_label("exit"), fn)

        bb = fn.get_basic_block()
        bb.append_instruction("jmp", entry_block.label)
        fn.append_basic_block(entry_block)

        counter_var = entry_block.append_instruction("store", start)
        symbols[sym.value] = counter_var

        if bound is not None:
            # assert le end bound
            invalid_end = entry_block.append_instruction("gt", bound, end)
            valid_end = entry_block.append_instruction("iszero", invalid_end)
            entry_block.append_instruction("assert", valid_end)

        end = entry_block.append_instruction("add", start, end)

        entry_block.append_instruction("jmp", cond_block.label)

        xor_ret = cond_block.append_instruction("xor", counter_var, end)
        cont_ret = cond_block.append_instruction("iszero", xor_ret)
        fn.append_basic_block(cond_block)

        fn.append_basic_block(body_block)

        emit_body_blocks()
        body_end = fn.get_basic_block()
        if body_end.is_terminated is False:
            body_end.append_instruction("jmp", incr_block.label)

        fn.append_basic_block(incr_block)
        incr_block.insert_instruction(
            IRInstruction("add", [counter_var, IRLiteral(1)], counter_var)
        )
        incr_block.append_instruction("jmp", cond_block.label)

        fn.append_basic_block(exit_block)

        cond_block.append_instruction("jnz", cont_ret, exit_block.label, body_block.label)
    elif ir.value == "break":
        assert _break_target is not None, "Break with no break target"
        fn.get_basic_block().append_instruction("jmp", _break_target.label)
        fn.append_basic_block(IRBasicBlock(ctx.get_next_label(), fn))
    elif ir.value == "continue":
        assert _continue_target is not None, "Continue with no contrinue target"
        fn.get_basic_block().append_instruction("jmp", _continue_target.label)
        fn.append_basic_block(IRBasicBlock(ctx.get_next_label(), fn))
    elif ir.value in NOOP_INSTRUCTIONS:
        pass
    elif isinstance(ir.value, str) and ir.value.startswith("log"):
        args = reversed(_convert_ir_bb_list(fn, ir.args, symbols))
        topic_count = int(ir.value[3:])
        assert topic_count >= 0 and topic_count <= 4, "invalid topic count"
        fn.get_basic_block().append_instruction("log", topic_count, *args)
    elif isinstance(ir.value, str) and ir.value.upper() in get_opcodes():
        _convert_ir_opcode(fn, ir, symbols)
    elif isinstance(ir.value, str):
        if ir.value.startswith("$alloca") and ir.value not in _global_symbols:
            alloca = ir.passthrough_metadata["alloca"]
            ptr = fn.get_basic_block().append_instruction("alloca", alloca.offset, alloca.size)
            _global_symbols[ir.value] = ptr
        elif ir.value.startswith("$palloca") and ir.value not in _global_symbols:
            alloca = ir.passthrough_metadata["alloca"]
            ptr = fn.get_basic_block().append_instruction("store", alloca.offset)
            _global_symbols[ir.value] = ptr

        return _global_symbols.get(ir.value) or symbols.get(ir.value)
    elif ir.is_literal:
        return IRLiteral(ir.value)
    else:
        raise Exception(f"Unknown IR node: {ir}")

    return None


def _convert_ir_opcode(fn: IRFunction, ir: IRnode, symbols: SymbolTable) -> None:
    opcode = ir.value.upper()  # type: ignore
    inst_args = []
    for arg in ir.args:
        if isinstance(arg, IRnode):
            inst_args.append(_convert_ir_bb(fn, arg, symbols))
    fn.get_basic_block().append_instruction(opcode, *inst_args)
