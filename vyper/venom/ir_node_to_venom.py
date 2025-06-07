from __future__ import annotations

import contextlib
import functools
import re
from collections import defaultdict
from typing import Optional

from vyper.codegen.context import Alloca
from vyper.codegen.ir_node import IRnode
from vyper.ir.compile_ir import _runtime_code_offsets
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction, IRParameter

ENABLE_NEW_CALL_CONV = True
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
        "return",
        "returndatasize",
        "iload",
        "istore",
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
    ]
)

NOOP_INSTRUCTIONS = frozenset(["pass", "cleanup_repeat", "var_list", "unique_symbol"])

SymbolTable = dict[str, IROperand]
MAIN_ENTRY_LABEL_NAME = "__main_entry"


class IRnodeToVenom:
    _alloca_table: dict[int, IROperand]
    _callsites: dict[str, list[Alloca]]

    _scratch_alloca_id: int = 2**32

    # current vyper function
    _current_func_t = None

    _break_target: Optional[IRBasicBlock] = None
    _continue_target: Optional[IRBasicBlock] = None

    constants: dict[str, int]

    def __init__(self, constants: dict[str, int]):
        self._alloca_table = {}
        self._callsites = defaultdict(list)

        self.constants = constants

    def convert(self, ir: IRnode) -> IRContext:
        ctx = IRContext()
        fn = ctx.create_function(MAIN_ENTRY_LABEL_NAME)
        ctx.entry_function = fn

        self.variables = {}

        self.fn = fn
        self.convert_ir(ir)

        self.finish(ctx)

        return ctx

    def finish(self, ctx: IRContext):
        for fn in ctx.functions.values():
            for bb in fn.get_basic_blocks():
                bb.ensure_well_formed()

    def get_scratch_alloca_id(self):
        self._scratch_alloca_id += 1
        return self._scratch_alloca_id

    def convert_ir(self, ir: IRnode):
        _ = ir.unique_symbols  # run unique symbols check

        self.fn.push_source(ir)
        ret = self._convert_ir(ir)
        self.fn.pop_source()

        return ret

    @contextlib.contextmanager
    def anchor_fn(self, new_fn: IRFunction):
        tmp = self.fn
        try:
            self.fn = new_fn
            yield
        finally:
            self.fn = tmp

    @contextlib.contextmanager
    def anchor_variables(self, new_variables: Optional[SymbolTable] = None):
        if new_variables is None:
            new_variables = self.variables.copy()

        tmp = self.variables
        try:
            self.variables = new_variables
            yield
        finally:
            self.variables = tmp

    # globally agreed upon ret_ofst/ret_size variables
    RET_OFST = IRVariable("ret_ofst")
    RET_SIZE = IRVariable("ret_size")

    def _append_return_args(self, ofst: int, size: int):
        fn = self.fn
        bb = fn.get_basic_block()
        if bb.is_terminated:
            # NOTE: this generates dead code
            bb = IRBasicBlock(fn.ctx.get_next_label("exit_to"), fn)
            fn.append_basic_block(bb)

        bb.append_instruction("store", ofst, ret=self.RET_OFST)
        bb.append_instruction("store", size, ret=self.RET_SIZE)

    def _convert_ir_simple(self, ir: IRnode) -> Optional[IRVariable]:
        # execute in order
        args = self._convert_ir_list(ir.args)
        # reverse output variables for stack
        args.reverse()
        assert isinstance(ir.value, str)  # help mypy
        return self.fn.get_basic_block().append_instruction(ir.value, *args)

    def _convert_ir_list(self, ir_list: list[IRnode]):
        return [self.convert_ir(ir_node) for ir_node in ir_list]

    def _convert_ir(self, ir: IRnode):
        fn = self.fn
        ctx = fn.ctx

        if isinstance(ir.value, int):
            return IRLiteral(ir.value)

        elif ir.value in INVERSE_MAPPED_IR_INSTRUCTIONS:
            orig_value = ir.value
            ir.value = INVERSE_MAPPED_IR_INSTRUCTIONS[ir.value]
            new_var = self._convert_ir_simple(ir)
            assert new_var is not None  # help mypy
            ir.value = orig_value
            return fn.get_basic_block().append_instruction("iszero", new_var)

        elif ir.value in PASS_THROUGH_INSTRUCTIONS:
            return self._convert_ir_simple(ir)

        elif ir.value == "deploy":
            ctor_mem_size = ir.args[0].value
            immutables_len = ir.args[2].value
            runtime_codesize = self.constants["runtime_codesize"]
            assert immutables_len == self.constants["immutables_len"]  # sanity

            mem_deploy_start, mem_deploy_end = _runtime_code_offsets(
                ctor_mem_size, runtime_codesize
            )

            fn.ctx.add_constant("mem_deploy_end", mem_deploy_end)

            bb = fn.get_basic_block()

            bb.append_instruction(
                "codecopy", runtime_codesize, IRLabel("runtime_begin"), mem_deploy_start
            )
            amount_to_return = bb.append_instruction("add", runtime_codesize, immutables_len)
            bb.append_instruction("return", amount_to_return, mem_deploy_start)
            return None

        elif ir.value == "seq":
            if len(ir.args) == 0:
                return None
            if ir.is_self_call:
                return self._handle_self_call(ir)
            elif ir.args[0].value == "label":
                current_func = ir.args[0].args[0].value
                is_external = current_func.startswith("external")
                is_internal = current_func.startswith("internal")
                if (
                    is_internal
                    or len(re.findall(r"external.*__init__\(.*_deploy", current_func)) > 0
                ):
                    # Internal definition
                    var_list = ir.args[0].args[1]
                    assert var_list.value == "var_list"

                    does_return_data = IRnode.from_list(["return_buffer"]) in var_list.args

                    new_variables = {}
                    with self.anchor_variables(new_variables):
                        new_fn = self._handle_internal_func(ir, does_return_data)
                        with self.anchor_fn(new_fn):
                            for ir_node in ir.args[1:]:
                                ret = self.convert_ir(ir_node)

                    return None

                assert is_external

                # "parameters" to the exit sequence block
                self.variables["ret_ofst"] = self.RET_OFST
                self.variables["ret_len"] = self.RET_SIZE
                ret = self.convert_ir(ir.args[0])

            else:
                bb = fn.get_basic_block()
                if bb.is_terminated:
                    bb = IRBasicBlock(ctx.get_next_label("seq"), fn)
                    fn.append_basic_block(bb)
                ret = self.convert_ir(ir.args[0])

            for ir_node in ir.args[1:]:
                # seq returns the last item in the list
                ret = self.convert_ir(ir_node)

            return ret

        elif ir.value == "if":
            return self._handle_if_stmt(ir)

        elif ir.value == "with":
            varname = ir.args[0]

            # compute the initial value for the variable
            ret = self.convert_ir(ir.args[1])
            # ensure it is stored in a variable
            ret = fn.get_basic_block().append_instruction("store", ret)

            body_ir = ir.args[2]
            with self.anchor_variables():
                assert isinstance(varname.value, str)
                # `with` allows shadowing
                self.variables[varname.value] = ret
                return self.convert_ir(body_ir)

        elif ir.value == "goto":
            bb = fn.get_basic_block()

            if bb.is_terminated:
                # TODO: this branch seems dead, investigate.
                bb = IRBasicBlock(fn.ctx.get_next_label("jmp_target"), fn)
                fn.append_basic_block(bb)

            bb.append_instruction("jmp", IRLabel(ir.args[0].value))

        elif ir.value == "djump":
            args = [self.convert_ir(ir.args[0])]
            for target in ir.args[1:]:
                args.append(IRLabel(target.value))
            fn.get_basic_block().append_instruction("djmp", *args)
            self._append_new_bb()
            return

        elif ir.value == "set":
            varname = ir.args[0].value
            assert isinstance(varname, str)
            arg_1 = self.convert_ir(ir.args[1])
            venom_var = self.variables[varname]
            fn.get_basic_block().append_instruction("store", arg_1, ret=venom_var)
            return

        elif ir.value == "symbol":
            return IRLabel(ir.args[0].value, True)

        elif ir.value == "data":
            label = IRLabel(ir.args[0].value, True)
            ctx.append_data_section(label)
            for c in ir.args[1:]:
                if isinstance(c.value, bytes):
                    ctx.append_data_item(c.value)
                elif isinstance(c, IRnode):
                    data = self.convert_ir(c)
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
            self.convert_ir(code)

        elif ir.value == "exit_to":
            bb = fn.get_basic_block()
            if bb.is_terminated:
                bb = IRBasicBlock(ctx.get_next_label("exit_to"), fn)
                fn.append_basic_block(bb)

            args = self._convert_ir_list(ir.args[1:])
            bb = fn.get_basic_block()

            label = IRLabel(ir.args[0].value)
            if label.value == "return_pc":
                # return from internal function

                label = self.variables["return_pc"]
                # return label should be top of stack
                if _returns_word(self._current_func_t) and ENABLE_NEW_CALL_CONV:
                    buf = self.variables["return_buffer"]
                    val = bb.append_instruction("mload", buf)
                    bb.append_instruction("ret", val, label)
                else:
                    bb.append_instruction("ret", label)

            elif len(ir.args) > 1 and ir.args[1].value == "return_pc":
                # cleanup routine for internal function
                bb.append_instruction("jmp", label)
            else:
                # cleanup routine for external function
                if len(args) > 0:
                    ofst, size = args
                    self._append_return_args(ofst, size)
                bb = fn.get_basic_block()
                bb.append_instruction("jmp", label)

        elif ir.value == "mstore":
            # some upstream code depends on reversed order of evaluation --
            # to fix upstream.
            val, ptr = self._convert_ir_list(reversed(ir.args))
            return fn.get_basic_block().append_instruction("mstore", val, ptr)

        elif ir.value == "ceil32":
            x = ir.args[0]
            expanded = IRnode.from_list(["and", ["add", x, 31], ["not", 31]])
            return self.convert_ir(expanded)

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
            return self.convert_ir(expanded)

        elif ir.value == "repeat":
            return self._handle_repeat(ir)

        elif ir.value == "break":
            assert self._break_target is not None
            fn.get_basic_block().append_instruction("jmp", self._break_target.label)
            self._append_new_bb()

        elif ir.value == "continue":
            assert self._continue_target is not None
            fn.get_basic_block().append_instruction("jmp", self._continue_target.label)
            self._append_new_bb()

        elif ir.value in NOOP_INSTRUCTIONS:
            pass

        elif isinstance(ir.value, str) and ir.value.startswith("log"):
            args = reversed(self._convert_ir_list(ir.args))
            topic_count = int(ir.value[3:])
            assert topic_count >= 0 and topic_count <= 4, "invalid topic count"
            fn.get_basic_block().append_instruction("log", topic_count, *args)

        elif isinstance(ir.value, str):
            if ir.value.startswith("$alloca"):
                alloca = ir.passthrough_metadata["alloca"]
                if alloca._id not in self._alloca_table:
                    ptr = fn.get_basic_block().append_instruction(
                        "alloca", alloca.offset, alloca.size, alloca._id
                    )
                    self._alloca_table[alloca._id] = ptr
                return self._alloca_table[alloca._id]

            elif ir.value.startswith("$palloca"):
                alloca = ir.passthrough_metadata["alloca"]
                if alloca._id not in self._alloca_table:
                    bb = fn.get_basic_block()
                    ptr = bb.append_instruction("palloca", alloca.offset, alloca.size, alloca._id)
                    bb.instructions[-1].annotation = f"{alloca.name} (memory)"
                    if ENABLE_NEW_CALL_CONV and _pass_via_stack(self._current_func_t)[alloca.name]:
                        param = fn.get_param_by_id(alloca._id)
                        assert param is not None
                        bb.append_instruction("mstore", param.func_var, ptr)
                    self._alloca_table[alloca._id] = ptr
                return self._alloca_table[alloca._id]
            elif ir.value.startswith("$calloca"):
                alloca = ir.passthrough_metadata["alloca"]
                assert alloca._callsite is not None
                if alloca._id not in self._alloca_table:
                    bb = fn.get_basic_block()

                    callsite_func = ir.passthrough_metadata["callsite_func"]
                    if ENABLE_NEW_CALL_CONV and _pass_via_stack(callsite_func)[alloca.name]:
                        ptr = bb.append_instruction(
                            "alloca", alloca.offset, alloca.size, alloca._id
                        )
                    else:
                        # if we use alloca, mstores might get removed. convert
                        # to calloca until memory analysis is more sound.
                        ptr = bb.append_instruction(
                            "calloca", alloca.offset, alloca.size, alloca._id
                        )

                    self._alloca_table[alloca._id] = ptr
                ret = self._alloca_table[alloca._id]
                # assumption: callocas appear in the same order as the
                # order of arguments to the function.
                self._callsites[alloca._callsite].append(alloca)
                return ret

            return self.variables[ir.value]

        else:
            raise Exception(f"Unknown IR node: {ir}")

        return None

    def _handle_if_stmt(self, ir: IRnode) -> Optional[IRVariable]:
        fn = self.fn
        ctx = fn.ctx

        cond_ir = ir.args[0]

        cond = self.convert_ir(cond_ir)
        cond_block = fn.get_basic_block()

        then_block = IRBasicBlock(ctx.get_next_label("then"), fn)
        else_block = IRBasicBlock(ctx.get_next_label("else"), fn)

        # convert "then"
        fn.append_basic_block(then_block)
        with self.anchor_variables():
            then_ret_val = self.convert_ir(ir.args[1])

        then_block_finish = fn.get_basic_block()

        # convert "else"
        fn.append_basic_block(else_block)
        else_ret_val = None
        if len(ir.args) == 3:
            with self.anchor_variables():
                else_ret_val = self.convert_ir(ir.args[2])

        else_block_finish = fn.get_basic_block()

        # finish the condition block
        cond_block.append_instruction("jnz", cond, then_block.label, else_block.label)

        # exit bb
        join_bb = IRBasicBlock(ctx.get_next_label("if_exit"), fn)
        fn.append_basic_block(join_bb)

        if_ret = fn.get_next_variable()
        # will get converted to phi by make_ssa
        if then_ret_val is not None and else_ret_val is not None:
            then_block_finish.append_instruction("store", then_ret_val, ret=if_ret)
            else_block_finish.append_instruction("store", else_ret_val, ret=if_ret)

        if not else_block_finish.is_terminated:
            else_block_finish.append_instruction("jmp", join_bb.label)

        if not then_block_finish.is_terminated:
            then_block_finish.append_instruction("jmp", join_bb.label)

        return if_ret

    def _handle_repeat(self, ir):
        fn = self.fn
        ctx = fn.ctx

        # loop variable name
        sym = ir.args[0]
        start, end, _ = self._convert_ir_list(ir.args[1:4])

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

        if bound is not None:
            # assert le end bound
            invalid_end = entry_block.append_instruction("gt", bound, end)
            valid_end = entry_block.append_instruction("iszero", invalid_end)
            entry_block.append_instruction("assert", valid_end)

        end = entry_block.append_instruction("add", start, end)

        entry_block.append_instruction("jmp", cond_block.label)

        xor_ret = cond_block.append_instruction("xor", counter_var, end)
        cond = cond_block.append_instruction("iszero", xor_ret)

        fn.append_basic_block(cond_block)

        # convert body
        fn.append_basic_block(body_block)
        backup = self._break_target, self._continue_target
        self._break_target = exit_block
        self._continue_target = incr_block
        with self.anchor_variables():
            self.variables[sym.value] = counter_var
            self.convert_ir(body)
        self._break_target, self._continue_target = backup

        body_end = fn.get_basic_block()
        if body_end.is_terminated is False:
            body_end.append_instruction("jmp", incr_block.label)

        fn.append_basic_block(incr_block)
        incr_block.insert_instruction(
            IRInstruction("add", [counter_var, IRLiteral(1)], counter_var)
        )
        incr_block.append_instruction("jmp", cond_block.label)

        fn.append_basic_block(exit_block)

        cond_block.append_instruction("jnz", cond, exit_block.label, body_block.label)

    def _handle_self_call(self, ir: IRnode) -> Optional[IROperand]:
        fn = self.fn

        setup_ir = ir.args[1]
        goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
        target_label = goto_ir.args[0].value  # goto

        func_t = ir.passthrough_metadata["func_t"]
        assert func_t is not None, "func_t not found in passthrough metadata"

        returns_word = _returns_word(func_t)

        if setup_ir != goto_ir:
            self.convert_ir(setup_ir)

        converted_args = self._convert_ir_list(goto_ir.args[1:])

        callsite_op = converted_args[-1]
        assert isinstance(callsite_op, IRLabel), converted_args
        callsite = callsite_op.value

        bb = fn.get_basic_block()
        return_buf = None

        if len(converted_args) > 1:
            return_buf = converted_args[0]

        stack_args: list[IROperand] = [IRLabel(str(target_label))]

        if return_buf is not None:
            if not ENABLE_NEW_CALL_CONV or not returns_word:
                stack_args.append(return_buf)

        callsite_args = self._callsites[callsite]
        if ENABLE_NEW_CALL_CONV:
            for alloca in callsite_args:
                if not _pass_via_stack(func_t)[alloca.name]:
                    continue
                ptr = self._alloca_table[alloca._id]
                stack_arg = bb.append_instruction("mload", ptr)
                assert stack_arg is not None
                stack_args.append(stack_arg)

            if returns_word:
                ret_value = bb.append_invoke_instruction(stack_args, returns=True)
                assert ret_value is not None  # help mypy
                assert return_buf is not None  # help mypy
                bb.append_instruction("mstore", ret_value, return_buf)
                return return_buf

        bb.append_invoke_instruction(stack_args, returns=False)

        return return_buf

    # TODO: remove does_return_data, replace with `func_t.return_type is not None`
    def _handle_internal_func(self, ir: IRnode, does_return_data: bool) -> IRFunction:
        fn = self.fn

        func_t = ir.passthrough_metadata["func_t"]
        context = ir.passthrough_metadata["context"]
        assert func_t is not None, "func_t not found in passthrough metadata"
        assert context is not None, func_t.name

        self._current_func_t = func_t

        funcname = ir.args[0].args[0].value
        assert isinstance(funcname, str)
        fn = fn.ctx.create_function(funcname)

        bb = fn.get_basic_block()

        _saved_alloca_table = self._alloca_table
        self._alloca_table = {}

        returns_word = _returns_word(func_t)

        # return buffer
        if does_return_data:
            if ENABLE_NEW_CALL_CONV and returns_word:
                # TODO: remove this once we have proper memory allocator
                # functionality in venom. Currently, we hardcode the scratch
                # buffer size of 32 bytes.
                # TODO: we don't need to use scratch space once the legacy optimizer
                # is disabled.
                buf = bb.append_instruction("alloca", 0, 32, self.get_scratch_alloca_id())
            else:
                buf = bb.append_instruction("param")
                bb.instructions[-1].annotation = "return_buffer"

            assert buf is not None  # help mypy
            self.variables["return_buffer"] = buf

        if ENABLE_NEW_CALL_CONV:
            stack_index = 0
            if func_t.return_type is not None and not _returns_word(func_t):
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
        self.variables["return_pc"] = return_pc
        bb.instructions[-1].annotation = "return_pc"

        with self.anchor_fn(fn):
            # convert the body of the function
            self.convert_ir(ir.args[0].args[2])

        self._alloca_table = _saved_alloca_table

        return fn

    def _append_new_bb(self) -> None:
        fn = self.fn
        bb = IRBasicBlock(fn.ctx.get_next_label(), fn)
        fn.append_basic_block(bb)


# func_t: ContractFunctionT
@functools.lru_cache(maxsize=1024)
def _pass_via_stack(func_t) -> dict[str, bool]:
    # returns a dict which returns True if a given argument (referered to
    # by name) should be passed via the stack
    if not ENABLE_NEW_CALL_CONV:
        return {arg.name: False for arg in func_t.arguments}

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


def _is_word_type(typ):
    # we can pass it on the stack.
    return typ.memory_bytes_required == 32


# func_t: ContractFunctionT
def _returns_word(func_t) -> bool:
    return_t = func_t.return_type
    return return_t is not None and _is_word_type(return_t)


def ir_node_to_venom(ir: IRnode, constants: Optional[dict[str, int]]) -> IRContext:
    constants = constants or {}
    return IRnodeToVenom(constants).convert(ir)
