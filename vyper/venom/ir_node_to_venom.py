from __future__ import annotations

import functools
import re
from collections import defaultdict
from typing import Optional

from vyper.codegen.context import Alloca
from vyper.codegen.core import is_tuple_like
from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import get_opcodes, version_check
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import DeployInfo, IRContext
from vyper.venom.function import IRFunction, IRParameter
from vyper.venom.memory_location import Allocation

# Experimental: allow returning multiple 32-byte values via the stack
ENABLE_MULTI_RETURNS = True
MAX_STACK_RETURNS = 2
MAX_STACK_ARGS = 6

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
        "dload",
        "dloadbytes",
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
        "sink",
    ]
)

NOOP_INSTRUCTIONS = frozenset(["pass", "cleanup_repeat", "var_list", "unique_symbol"])

SymbolTable = dict[str, IROperand]
_alloca_table: dict[int, IROperand]
_callsites: dict[str, list[Alloca]]
_immutable_alloca_id: Optional[int]
_immutables_region_alloca: Optional[IRInstruction]
MAIN_ENTRY_LABEL_NAME = "__main_entry"

_scratch_alloca_id = 2**32


def get_scratch_alloca_id() -> int:
    global _scratch_alloca_id
    _scratch_alloca_id += 1
    return _scratch_alloca_id


# convert IRnode directly to venom
def ir_node_to_venom(ir: IRnode, deploy_info: Optional[DeployInfo] = None) -> IRContext:
    _ = ir.unique_symbols  # run unique symbols check

    global _alloca_table, _callsites, _immutable_alloca_id, _immutables_region_alloca
    _alloca_table = {}
    _callsites = defaultdict(list)

    symbols: SymbolTable = {}

    ctx = IRContext()

    fn = ctx.create_function(MAIN_ENTRY_LABEL_NAME)
    ctx.entry_function = fn

    _immutable_alloca_id = None
    _immutables_region_alloca = None
    if deploy_info is not None:
        bb = fn.get_basic_block()
        # TODO: get rid of the alloca_id -- maybe Context.global_allocations
        _immutable_alloca_id = get_scratch_alloca_id()
        inst = IRInstruction(
            "alloca",
            [IRLiteral(deploy_info.immutables_len), IRLiteral(_immutable_alloca_id)],
            outputs=[fn.get_next_variable()],
            annotation="immutables region",
        )
        bb.insert_instruction(inst)
        _immutables_region_alloca = inst
        allocation = Allocation(_immutables_region_alloca)
        ctx.mem_allocator.set_position(allocation, 0)
        ctx.mem_allocator.add_global(allocation)
        symbols["runtime_codesize"] = IRLiteral(deploy_info.runtime_codesize)

    _convert_ir_bb(fn, ir, symbols)

    for fn in ctx.functions.values():
        for bb in fn.get_basic_blocks():
            bb.ensure_well_formed()

    del _immutable_alloca_id  # hygiene
    del _immutables_region_alloca  # hygiene

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
    bb.append_instruction("assign", ofst, ret=ret_ofst)
    bb.append_instruction("assign", size, ret=ret_size)


# func_t: ContractFunctionT
@functools.lru_cache(maxsize=1024)
def _pass_via_stack(func_t) -> dict[str, bool]:
    # returns a dict which returns True if a given argument (referred to
    # by name) should be passed via the stack
    arguments = {arg.name: arg for arg in func_t.arguments}

    stack_items = 0
    returns_word = _returns_word(func_t)
    if returns_word:
        stack_items += 1

    ret = {}

    for arg in arguments.values():
        if not _is_word_type(arg.typ) or stack_items > MAX_STACK_ARGS:
            ret[arg.name] = False
        else:
            ret[arg.name] = True
            stack_items += 1

    return ret


def _handle_self_call(fn: IRFunction, ir: IRnode, symbols: SymbolTable) -> Optional[IROperand]:
    global _callsites
    setup_ir = ir.args[1]
    goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
    target_label = goto_ir.args[0].value  # goto

    func_t = ir.passthrough_metadata["func_t"]
    assert func_t is not None, "func_t not found in passthrough metadata"

    returns_count = _returns_stack_count(func_t)

    if setup_ir != goto_ir:
        _convert_ir_bb(fn, setup_ir, symbols)

    converted_args = _convert_ir_bb_list(fn, goto_ir.args[1:], symbols)

    callsite_op = converted_args[-1]
    assert isinstance(callsite_op, IRLabel), converted_args
    callsite = callsite_op.value

    bb = fn.get_basic_block()
    return_buf: Optional[IROperand] = None
    # If a return buffer pointer is supplied by upstream IR, use it
    if len(converted_args) > 1:
        return_buf = converted_args[0]

    # For multi-return via stack without a provided buffer, synthesize one
    if returns_count > 0 and return_buf is None:
        return_buf = bb.append_instruction1(
            "alloca", 32 * returns_count, get_scratch_alloca_id(), annotation="return buffer"
        )

    stack_args: list[IROperand] = [IRLabel(str(target_label))]

    if return_buf is not None:
        if returns_count == 0:
            stack_args.append(return_buf)

    callsite_args = _callsites[callsite]
    for alloca in callsite_args:
        if not _pass_via_stack(func_t)[alloca.name]:
            continue
        ptr = _alloca_table[alloca._id]
        stack_arg = bb.append_instruction("mload", ptr)
        assert stack_arg is not None
        stack_args.append(stack_arg)

    if returns_count > 0:
        outs = bb.append_invoke_instruction(stack_args, returns=returns_count)
        assert return_buf is not None  # help mypy
        # copy the output stack args into caller-provided memory (to
        # be lifted by mem2var later)
        for i, outv in enumerate(outs):
            ofst = IRLiteral(32 * i)
            dst = bb.append_instruction1("add", return_buf, ofst)
            bb.append_instruction("mstore", outv, dst)

    else:
        bb.append_invoke_instruction(stack_args, returns=0)

    return return_buf


_current_func_t = None


def _is_word_type(typ):
    # we can pass it on the stack.
    return typ.memory_bytes_required == 32


# func_t: ContractFunctionT
def _returns_word(func_t) -> bool:
    return_t = func_t.return_type
    return return_t is not None and _is_word_type(return_t)


def _returns_stack_count(func_t) -> int:
    ret_t = func_t.return_type
    if ret_t is None:
        return 0
    if ENABLE_MULTI_RETURNS and is_tuple_like(ret_t):
        members = ret_t.tuple_items()
        if 1 <= len(members) <= MAX_STACK_RETURNS and all(_is_word_type(t) for (_k, t) in members):
            return len(members)
        return 0
    return 1 if _is_word_type(ret_t) else 0


def _handle_internal_func(
    # TODO: remove does_return_data, replace with `func_t.return_type is not None`
    fn: IRFunction,
    ir: IRnode,
    does_return_data: bool,
    symbols: SymbolTable,
) -> IRFunction:
    global _alloca_table, _current_func_t, _immutable_alloca_id, _immutables_region_alloca

    func_t = ir.passthrough_metadata["func_t"]
    context = ir.passthrough_metadata["context"]
    assert func_t is not None, "func_t not found in passthrough metadata"
    assert context is not None, func_t.name

    _current_func_t = func_t

    funcname = ir.args[0].args[0].value
    assert isinstance(funcname, str)
    fn = fn.ctx.create_function(funcname)

    bb = fn.get_basic_block()

    _saved_alloca_table = _alloca_table
    _alloca_table = {}

    returns_count = _returns_stack_count(func_t)

    if _immutable_alloca_id is not None:
        assert _immutables_region_alloca is not None
        size = _immutables_region_alloca.operands[0]
        inst = IRInstruction(
            "alloca",
            [size, IRLiteral(_immutable_alloca_id)],
            outputs=[fn.get_next_variable()],
            annotation="immutables region",
        )
        bb.insert_instruction(inst)
        _immutables_region_alloca = inst
        fn.ctx.mem_allocator.set_position(Allocation(inst), 0)

    # return buffer
    if does_return_data:
        if returns_count > 0:
            buf = bb.append_instruction(
                "alloca", 32 * returns_count, get_scratch_alloca_id(), annotation="return buffer"
            )
        else:
            buf = bb.append_instruction("param")
            bb.instructions[-1].annotation = "return_buffer"

        assert buf is not None  # help mypy
        symbols["return_buffer"] = buf

    stack_index = 0
    if func_t.return_type is not None and _returns_stack_count(func_t) == 0:
        stack_index += 1
    for arg in func_t.arguments:
        if not _pass_via_stack(func_t)[arg.name]:
            continue

        param = bb.append_instruction("param")
        bb.instructions[-1].annotation = arg.name
        assert param is not None  # help mypy

        var = context.lookup_var(arg.name)

        venom_arg = IRParameter(
            name=var.name,
            index=stack_index,
            offset=var.alloca.offset,
            size=var.alloca.size,
            id_=var.alloca._id,
            call_site_var=None,
            func_var=param,
            addr_var=None,
        )
        fn.args.append(venom_arg)
        stack_index += 1

    # return address
    return_pc = bb.append_instruction("param")
    assert return_pc is not None  # help mypy
    symbols["return_pc"] = return_pc
    bb.instructions[-1].annotation = "return_pc"

    # convert the body of the function
    _convert_ir_bb(fn, ir.args[0].args[2], symbols)

    _alloca_table = _saved_alloca_table

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
    global _break_target, _continue_target, _alloca_table
    global _immutables_region

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
    elif ir.value == "sha3_64":
        first = _convert_ir_bb(fn, ir.args[0], symbols)
        second = _convert_ir_bb(fn, ir.args[1], symbols)
        bb = fn.get_basic_block()
        buf = bb.append_instruction("alloca", 64, get_scratch_alloca_id())
        bb.append_instruction("mstore", second, buf)
        next_part = bb.append_instruction("gep", buf, 32)
        bb.append_instruction("mstore", first, next_part)
        return bb.append_instruction("sha3", 64, buf)
    elif ir.value == "return":
        fn.get_basic_block().append_instruction(
            "return", IRVariable("ret_size"), IRVariable("ret_ofst")
        )
    elif ir.value == "deploy":
        immutables_len = ir.args[2].value
        runtime_codesize = symbols["runtime_codesize"].value

        bb = fn.get_basic_block()

        # copy runtime code to hardcode location
        # (use a location *after* FREE_VAR_SPACE2, otherwise it gets
        # mutilated by fix_mem_loc)
        dst = 64
        # copy immutables to end of runtime code
        immutables_dst = dst + runtime_codesize

        # see copy_bytes() in legacy pipeline
        # TODO: maybe have a helper function for this
        assert _immutables_region_alloca is not None
        if version_check(begin="cancun"):
            bb.append_instruction(
                "mcopy", immutables_len, _immutables_region_alloca.output, immutables_dst
            )
        else:
            gas = bb.append_instruction("gas")
            copy_success = bb.append_instruction(
                "staticcall",
                immutables_len,
                immutables_dst,
                immutables_len,
                _immutables_region_alloca.output,
                0x04,
                gas,
            )
            bb.append_instruction("assert", copy_success)

        bb.append_instruction("codecopy", runtime_codesize, IRLabel("runtime_begin"), dst)
        amount_to_return = bb.append_instruction("add", runtime_codesize, immutables_len)
        bb.append_instruction("return", amount_to_return, dst)
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
                assert var_list.value == "var_list"
                does_return_data = IRnode.from_list(["return_buffer"]) in var_list.args
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

        then_block = IRBasicBlock(ctx.get_next_label("then"), fn)
        else_block = IRBasicBlock(ctx.get_next_label("else"), fn)

        # convert "then"
        cond_symbols = symbols.copy()
        fn.append_basic_block(then_block)
        then_ret_val = _convert_ir_bb(fn, ir.args[1], cond_symbols)
        if isinstance(then_ret_val, IRLiteral):
            then_ret_val = fn.get_basic_block().append_instruction("assign", then_ret_val)

        then_block_finish = fn.get_basic_block()

        # convert "else"
        cond_symbols = symbols.copy()
        fn.append_basic_block(else_block)
        else_ret_val = None
        if len(ir.args) == 3:
            else_ret_val = _convert_ir_bb(fn, ir.args[2], cond_symbols)
            if isinstance(else_ret_val, IRLiteral):
                assert isinstance(else_ret_val.value, int)  # help mypy
                else_ret_val = fn.get_basic_block().append_instruction("assign", else_ret_val)

        else_block_finish = fn.get_basic_block()

        # finish the condition block
        cond_block.append_instruction("jnz", cont_ret, then_block.label, else_block.label)

        # exit bb
        exit_bb = IRBasicBlock(ctx.get_next_label("if_exit"), fn)
        fn.append_basic_block(exit_bb)

        if_ret = fn.get_next_variable()
        if then_ret_val is not None and else_ret_val is not None:
            then_block_finish.append_instruction("assign", then_ret_val, ret=if_ret)
            else_block_finish.append_instruction("assign", else_ret_val, ret=if_ret)

        if not else_block_finish.is_terminated:
            else_block_finish.append_instruction("jmp", exit_bb.label)

        if not then_block_finish.is_terminated:
            then_block_finish.append_instruction("jmp", exit_bb.label)

        return if_ret

    elif ir.value == "with":
        ret = _convert_ir_bb(fn, ir.args[1], symbols)  # initialization

        ret = fn.get_basic_block().append_instruction("assign", ret)

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
        fn.get_basic_block().append_instruction("assign", arg_1, ret=symbols[sym.value])
    elif ir.value == "symbol":
        return IRLabel(ir.args[0].value, True)
    elif ir.value == "data":
        label = IRLabel(ir.args[0].value, True)
        ctx.append_data_section(label)
        for c in ir.args[1:]:
            if isinstance(c.value, bytes):
                ctx.append_data_item(c.value)
            elif isinstance(c, IRnode):
                data = _convert_ir_bb(fn, c, symbols)
                assert isinstance(data, IRLabel)  # help mypy
                ctx.append_data_item(data)
    elif ir.value == "label":
        label = IRLabel(ir.args[0].value, True)
        bb = fn.get_basic_block()
        if not bb.is_terminated:
            bb.append_instruction("jmp", label)
        bb = IRBasicBlock(label, fn)
        fn.append_basic_block(bb)
        code = ir.args[2]
        _convert_ir_bb(fn, code, symbols)
    elif ir.value == "exit_to":
        bb = fn.get_basic_block()
        if bb.is_terminated:
            bb = IRBasicBlock(ctx.get_next_label("exit_to"), fn)
            fn.append_basic_block(bb)

        args = _convert_ir_bb_list(fn, ir.args[1:], symbols)
        var_list = args
        # TODO: only append return args if the function is external
        _append_return_args(fn, *var_list)
        bb = fn.get_basic_block()

        label = IRLabel(ir.args[0].value)
        if label.value == "return_pc":
            label = symbols.get("return_pc")
            # return label should be top of stack
            k = _returns_stack_count(_current_func_t)
            if k > 0:
                buf = symbols["return_buffer"]
                ret_vals: list[IROperand] = []
                for i in range(k):
                    ofst = IRLiteral(32 * i)
                    ptr = bb.append_instruction1("add", buf, ofst)
                    val = bb.append_instruction1("mload", ptr)
                    ret_vals.append(val)
                bb.append_instruction("ret", *ret_vals, label)
            else:
                bb.append_instruction("ret", label)

        else:
            bb.append_instruction("jmp", label)

    elif ir.value == "mstore":
        # some upstream code depends on reversed order of evaluation --
        # to fix upstream.
        val, ptr = _convert_ir_bb_list(fn, reversed(ir.args), symbols)
        return fn.get_basic_block().append_instruction("mstore", val, ptr)

    elif ir.value == "iload":
        ofst = _convert_ir_bb(fn, ir.args[0], symbols)
        bb = fn.get_basic_block()
        assert _immutables_region_alloca is not None
        ptr = bb.append_instruction("gep", _immutables_region_alloca.output, ofst)
        return bb.append_instruction("mload", ptr)

    elif ir.value == "istore":
        ofst, val = _convert_ir_bb_list(fn, ir.args, symbols)
        bb = fn.get_basic_block()
        assert _immutables_region_alloca is not None
        ptr = bb.append_instruction("gep", _immutables_region_alloca.output, ofst)
        return bb.append_instruction("mstore", val, ptr)

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
            global _break_target, _continue_target
            old_targets = _break_target, _continue_target
            _break_target, _continue_target = exit_block, incr_block
            _convert_ir_bb(fn, body, symbols.copy())
            _break_target, _continue_target = old_targets

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

        counter_var = entry_block.append_instruction("assign", start)
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
            IRInstruction("add", [counter_var, IRLiteral(1)], [counter_var])
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
        if ir.value.startswith("$alloca"):
            alloca = ir.passthrough_metadata["alloca"]
            if alloca._id not in _alloca_table:
                # id is still needed for inlining
                ptr = fn.get_basic_block().append_instruction(
                    "alloca", alloca.size, alloca._id, annotation=alloca.name
                )
                _alloca_table[alloca._id] = ptr
            return _alloca_table[alloca._id]

        elif ir.value.startswith("$palloca"):
            assert isinstance(fn, IRFunction)
            alloca = ir.passthrough_metadata["alloca"]
            if alloca._id not in _alloca_table:
                bb = fn.get_basic_block()
                ptr = bb.append_instruction(
                    "palloca", alloca.size, alloca._id, annotation=alloca.name
                )
                bb.instructions[-1].annotation = f"{alloca.name} (memory)"
                fn.set_palloca(alloca._id, bb.instructions[-1])
                if _pass_via_stack(_current_func_t)[alloca.name]:
                    param = fn.get_param_by_id(alloca._id)
                    assert param is not None
                    # NOTE: The mstore MUST immediately follow the palloca.
                    # FloatAllocas pass depends on this invariant to move both
                    # instructions together to the entry block.
                    bb.append_instruction("mstore", param.func_var, ptr)
                _alloca_table[alloca._id] = ptr
            return _alloca_table[alloca._id]
        elif ir.value.startswith("$calloca"):
            global _callsites
            alloca = ir.passthrough_metadata["alloca"]
            assert alloca._callsite is not None
            if alloca._id not in _alloca_table:
                bb = fn.get_basic_block()

                callsite_func = ir.passthrough_metadata["callsite_func"]
                if _pass_via_stack(callsite_func)[alloca.name]:
                    ptr = bb.append_instruction(
                        "alloca", alloca.size, alloca._id, annotation=alloca.name
                    )
                else:
                    # if we use alloca, mstores might get removed. convert
                    # to calloca until memory analysis is more sound.
                    ptr = bb.append_instruction(
                        "calloca",
                        alloca.size,
                        alloca._id,
                        IRLabel(alloca._callsite),
                        annotation=alloca.name,
                    )

                _alloca_table[alloca._id] = ptr
            ret = _alloca_table[alloca._id]
            # assumption: callocas appear in the same order as the
            # order of arguments to the function.
            _callsites[alloca._callsite].append(alloca)
            return ret

        return symbols.get(ir.value)
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
