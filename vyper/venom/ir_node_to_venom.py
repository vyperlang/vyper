from typing import Optional

from vyper.codegen.context import VariableRecord
from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import get_opcodes
from vyper.exceptions import CompilerPanic
from vyper.ir.compile_ir import is_mem_sym, is_symbol
from vyper.semantics.types.function import ContractFunctionT
from vyper.utils import MemoryPositions, OrderedSet
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
    MemType,
)
from vyper.venom.function import IRFunction

_BINARY_IR_INSTRUCTIONS = frozenset(
    [
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
        "exp",
        "sha3",
        "sha3_64",
        "signextend",
    ]
)

# Instuctions that are mapped to their inverse
INVERSE_MAPPED_IR_INSTRUCTIONS = {"ne": "eq", "le": "gt", "sle": "sgt", "ge": "lt", "sge": "slt"}

# Instructions that have a direct EVM opcode equivalent and can
# be passed through to the EVM assembly without special handling
PASS_THROUGH_INSTRUCTIONS = [
    "chainid",
    "basefee",
    "timestamp",
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
    "coinbase",
    "number",
    "iszero",
    "ceil32",
    "calldataload",
    "extcodesize",
    "extcodehash",
    "balance",
]

SymbolTable = dict[str, IROperand]


def _get_symbols_common(a: dict, b: dict) -> dict:
    ret = {}
    # preserves the ordering in `a`
    for k in a.keys():
        if k not in b:
            continue
        if a[k] == b[k]:
            continue
        ret[k] = a[k], b[k]
    return ret


def convert_ir_basicblock(ir: IRnode) -> IRFunction:
    global_function = IRFunction()
    _convert_ir_basicblock(global_function, ir, {}, OrderedSet(), {})

    for i, bb in enumerate(global_function.basic_blocks):
        if not bb.is_terminated and i < len(global_function.basic_blocks) - 1:
            bb.append_instruction(IRInstruction("jmp", [global_function.basic_blocks[i + 1].label]))

    revert_bb = IRBasicBlock(IRLabel("__revert"), global_function)
    revert_bb = global_function.append_basic_block(revert_bb)
    revert_bb.append_instruction(IRInstruction("revert", [IRLiteral(0), IRLiteral(0)]))

    return global_function


def _convert_binary_op(
    ctx: IRFunction,
    ir: IRnode,
    symbols: SymbolTable,
    variables: OrderedSet,
    allocated_variables: dict[str, IRVariable],
    swap: bool = False,
) -> IRVariable:
    ir_args = ir.args[::-1] if swap else ir.args
    arg_0 = _convert_ir_basicblock(ctx, ir_args[0], symbols, variables, allocated_variables)
    arg_1 = _convert_ir_basicblock(ctx, ir_args[1], symbols, variables, allocated_variables)
    args = [arg_1, arg_0]

    ret = ctx.get_next_variable()

    inst = IRInstruction(ir.value, args, ret)  # type: ignore
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


def _handle_self_call(
    ctx: IRFunction,
    ir: IRnode,
    symbols: SymbolTable,
    variables: OrderedSet,
    allocated_variables: dict[str, IRVariable],
) -> Optional[IRVariable]:
    func_t = ir.passthrough_metadata.get("func_t", None)
    args_ir = ir.passthrough_metadata["args_ir"]
    goto_ir = [ir for ir in ir.args if ir.value == "goto"][0]
    target_label = goto_ir.args[0].value  # goto
    return_buf = goto_ir.args[1]  # return buffer
    ret_args = [IRLabel(target_label)]  # type: ignore

    for arg in args_ir:
        if arg.is_literal:
            sym = symbols.get(f"&{arg.value}", None)
            if sym is None:
                ret = _convert_ir_basicblock(ctx, arg, symbols, variables, allocated_variables)
                ret_args.append(ret)
            else:
                ret_args.append(sym)  # type: ignore
        else:
            ret = _convert_ir_basicblock(
                ctx, arg._optimized, symbols, variables, allocated_variables
            )
            if arg.location and arg.location.load_op == "calldataload":
                ret = ctx.append_instruction(arg.location.load_op, [ret])
            ret_args.append(ret)

    if return_buf.is_literal:
        ret_args.append(IRLiteral(return_buf.value))  # type: ignore

    do_ret = func_t.return_type is not None
    invoke_ret = ctx.append_instruction("invoke", ret_args, do_ret)  # type: ignore
    allocated_variables["return_buffer"] = invoke_ret  # type: ignore
    return invoke_ret


def _handle_internal_func(
    ctx: IRFunction, ir: IRnode, func_t: ContractFunctionT, symbols: SymbolTable
) -> IRnode:
    bb = IRBasicBlock(IRLabel(ir.args[0].args[0].value, True), ctx)  # type: ignore
    bb = ctx.append_basic_block(bb)

    old_ir_mempos = 0
    old_ir_mempos += 64

    for arg in func_t.arguments:
        new_var = ctx.get_next_variable()

        alloca_inst = IRInstruction("param", [], new_var)
        alloca_inst.annotation = arg.name
        bb.append_instruction(alloca_inst)
        symbols[f"&{old_ir_mempos}"] = new_var
        old_ir_mempos += 32  # arg.typ.memory_bytes_required

    # return buffer
    if func_t.return_type is not None:
        new_var = ctx.get_next_variable()
        alloca_inst = IRInstruction("param", [], new_var)
        bb.append_instruction(alloca_inst)
        alloca_inst.annotation = "return_buffer"
        symbols["return_buffer"] = new_var

    # return address
    new_var = ctx.get_next_variable()
    alloca_inst = IRInstruction("param", [], new_var)
    bb.append_instruction(alloca_inst)
    alloca_inst.annotation = "return_pc"
    symbols["return_pc"] = new_var

    return ir.args[0].args[2]


def _convert_ir_simple_node(
    ctx: IRFunction,
    ir: IRnode,
    symbols: SymbolTable,
    variables: OrderedSet,
    allocated_variables: dict[str, IRVariable],
) -> Optional[IRVariable]:
    args = [
        _convert_ir_basicblock(ctx, arg, symbols, variables, allocated_variables) for arg in ir.args
    ]
    return ctx.append_instruction(ir.value, args)  # type: ignore


_break_target: Optional[IRBasicBlock] = None
_continue_target: Optional[IRBasicBlock] = None


def _get_variable_from_address(
    variables: OrderedSet[VariableRecord], addr: int
) -> Optional[VariableRecord]:
    assert isinstance(addr, int), "non-int address"
    for var in variables.keys():
        if var.location.name != "memory":
            continue
        if addr >= var.pos and addr < var.pos + var.size:  # type: ignore
            return var
    return None


def _get_return_for_stack_operand(
    ctx: IRFunction, symbols: SymbolTable, ret_ir: IRVariable, last_ir: IRVariable
) -> IRInstruction:
    if isinstance(ret_ir, IRLiteral):
        sym = symbols.get(f"&{ret_ir.value}", None)
        new_var = ctx.append_instruction("alloca", [IRLiteral(32), ret_ir])
        ctx.append_instruction("mstore", [sym, new_var], False)  # type: ignore
    else:
        sym = symbols.get(ret_ir.value, None)
        if sym is None:
            # FIXME: needs real allocations
            new_var = ctx.append_instruction("alloca", [IRLiteral(32), IRLiteral(0)])
            ctx.append_instruction("mstore", [ret_ir, new_var], False)  # type: ignore
        else:
            new_var = ret_ir
    return IRInstruction("return", [last_ir, new_var])  # type: ignore


def _convert_ir_basicblock(ctx, ir, symbols, variables, allocated_variables):
    assert isinstance(variables, OrderedSet)
    global _break_target, _continue_target

    frame_info = ir.passthrough_metadata.get("frame_info", None)
    if frame_info is not None:
        local_vars = OrderedSet[VariableRecord](frame_info.frame_vars.values())
        variables |= local_vars

    assert isinstance(variables, OrderedSet)

    if ir.value in _BINARY_IR_INSTRUCTIONS:
        return _convert_binary_op(
            ctx, ir, symbols, variables, allocated_variables, ir.value in ["sha3_64"]
        )

    elif ir.value in INVERSE_MAPPED_IR_INSTRUCTIONS:
        org_value = ir.value
        ir.value = INVERSE_MAPPED_IR_INSTRUCTIONS[ir.value]
        new_var = _convert_binary_op(ctx, ir, symbols, variables, allocated_variables)
        ir.value = org_value
        return ctx.append_instruction("iszero", [new_var])

    elif ir.value in PASS_THROUGH_INSTRUCTIONS:
        return _convert_ir_simple_node(ctx, ir, symbols, variables, allocated_variables)

    elif ir.value in ["pass", "stop", "return"]:
        pass
    elif ir.value == "deploy":
        memsize = ir.args[0].value
        ir_runtime = ir.args[1]
        padding = ir.args[2].value
        assert isinstance(memsize, int), "non-int memsize"
        assert isinstance(padding, int), "non-int padding"

        runtimeLabel = ctx.get_next_label()

        inst = IRInstruction("deploy", [IRLiteral(memsize), runtimeLabel, IRLiteral(padding)])
        ctx.get_basic_block().append_instruction(inst)

        bb = IRBasicBlock(runtimeLabel, ctx)
        ctx.append_basic_block(bb)

        _convert_ir_basicblock(ctx, ir_runtime, symbols, variables, allocated_variables)
    elif ir.value == "seq":
        func_t = ir.passthrough_metadata.get("func_t", None)
        if ir.is_self_call:
            return _handle_self_call(ctx, ir, symbols, variables, allocated_variables)
        elif func_t is not None:
            symbols = {}
            allocated_variables = {}
            variables = OrderedSet(
                {v: True for v in ir.passthrough_metadata["frame_info"].frame_vars.values()}
            )
            if func_t.is_internal:
                ir = _handle_internal_func(ctx, ir, func_t, symbols)
            # fallthrough

        ret = None
        for ir_node in ir.args:  # NOTE: skip the last one
            ret = _convert_ir_basicblock(ctx, ir_node, symbols, variables, allocated_variables)

        return ret
    elif ir.value in ["staticcall", "call"]:  # external call
        idx = 0
        gas = _convert_ir_basicblock(ctx, ir.args[idx], symbols, variables, allocated_variables)
        address = _convert_ir_basicblock(
            ctx, ir.args[idx + 1], symbols, variables, allocated_variables
        )

        value = None
        if ir.value == "call":
            value = _convert_ir_basicblock(
                ctx, ir.args[idx + 2], symbols, variables, allocated_variables
            )
        else:
            idx -= 1

        argsOffset = _convert_ir_basicblock(
            ctx, ir.args[idx + 3], symbols, variables, allocated_variables
        )
        argsSize = _convert_ir_basicblock(
            ctx, ir.args[idx + 4], symbols, variables, allocated_variables
        )
        retOffset = _convert_ir_basicblock(
            ctx, ir.args[idx + 5], symbols, variables, allocated_variables
        )
        retSize = _convert_ir_basicblock(
            ctx, ir.args[idx + 6], symbols, variables, allocated_variables
        )

        if isinstance(argsOffset, IRLiteral):
            offset = int(argsOffset.value)
            addr = offset - 32 + 4 if offset > 0 else 0
            argsOffsetVar = symbols.get(f"&{addr}", None)
            if argsOffsetVar is None:
                argsOffsetVar = argsOffset
            elif isinstance(argsOffsetVar, IRVariable):
                argsOffsetVar.mem_type = MemType.MEMORY
                argsOffsetVar.mem_addr = addr
                argsOffsetVar.offset = 32 - 4 if offset > 0 else 0
            else:  # pragma: nocover
                raise CompilerPanic("unreachable")
        else:
            argsOffsetVar = argsOffset

        retOffsetValue = int(retOffset.value) if retOffset else 0
        retVar = ctx.get_next_variable(MemType.MEMORY, retOffsetValue)
        symbols[f"&{retOffsetValue}"] = retVar

        if ir.value == "call":
            args = [retSize, retOffset, argsSize, argsOffsetVar, value, address, gas]
            return ctx.append_instruction(ir.value, args)
        else:
            args = [retSize, retOffset, argsSize, argsOffsetVar, address, gas]
            return ctx.append_instruction(ir.value, args)
    elif ir.value == "if":
        cond = ir.args[0]
        current_bb = ctx.get_basic_block()

        # convert the condition
        cont_ret = _convert_ir_basicblock(ctx, cond, symbols, variables, allocated_variables)

        else_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(else_block)

        # convert "else"
        else_ret_val = None
        else_syms = symbols.copy()
        if len(ir.args) == 3:
            else_ret_val = _convert_ir_basicblock(
                ctx, ir.args[2], else_syms, variables, allocated_variables.copy()
            )
            if isinstance(else_ret_val, IRLiteral):
                assert isinstance(else_ret_val.value, int)  # help mypy
                else_ret_val = ctx.append_instruction("store", [IRLiteral(else_ret_val.value)])
        after_else_syms = else_syms.copy()

        # convert "then"
        then_block = IRBasicBlock(ctx.get_next_label(), ctx)
        ctx.append_basic_block(then_block)

        then_ret_val = _convert_ir_basicblock(
            ctx, ir.args[1], symbols, variables, allocated_variables
        )
        if isinstance(then_ret_val, IRLiteral):
            then_ret_val = ctx.append_instruction("store", [IRLiteral(then_ret_val.value)])

        inst = IRInstruction("jnz", [cont_ret, then_block.label, else_block.label])
        current_bb.append_instruction(inst)

        after_then_syms = symbols.copy()

        # exit bb
        exit_label = ctx.get_next_label()
        bb = IRBasicBlock(exit_label, ctx)
        bb = ctx.append_basic_block(bb)

        if_ret = None
        if then_ret_val is not None and else_ret_val is not None:
            if_ret = ctx.get_next_variable()
            bb.append_instruction(
                IRInstruction(
                    "phi", [then_block.label, then_ret_val, else_block.label, else_ret_val], if_ret
                )
            )

        common_symbols = _get_symbols_common(after_then_syms, after_else_syms)
        for sym, val in common_symbols.items():
            ret = ctx.get_next_variable()
            old_var = symbols.get(sym, None)
            symbols[sym] = ret
            if old_var is not None:
                for idx, var_rec in allocated_variables.items():  # type: ignore
                    if var_rec.value == old_var.value:
                        allocated_variables[idx] = ret  # type: ignore
            bb.append_instruction(
                IRInstruction("phi", [then_block.label, val[0], else_block.label, val[1]], ret)
            )

        if not else_block.is_terminated:
            exit_inst = IRInstruction("jmp", [bb.label])
            else_block.append_instruction(exit_inst)

        if not then_block.is_terminated:
            exit_inst = IRInstruction("jmp", [bb.label])
            then_block.append_instruction(exit_inst)

        return if_ret

    elif ir.value == "with":
        ret = _convert_ir_basicblock(
            ctx, ir.args[1], symbols, variables, allocated_variables
        )  # initialization

        # Handle with nesting with same symbol
        with_symbols = symbols.copy()

        sym = ir.args[0]
        if isinstance(ret, IRLiteral):
            new_var = ctx.append_instruction("store", [ret])  # type: ignore
            with_symbols[sym.value] = new_var
        else:
            with_symbols[sym.value] = ret  # type: ignore

        return _convert_ir_basicblock(
            ctx, ir.args[2], with_symbols, variables, allocated_variables
        )  # body
    elif ir.value == "goto":
        _append_jmp(ctx, IRLabel(ir.args[0].value))
    elif ir.value == "jump":
        arg_1 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        inst = IRInstruction("jmp", [arg_1])
        ctx.get_basic_block().append_instruction(inst)
        _new_block(ctx)
    elif ir.value == "set":
        sym = ir.args[0]
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        new_var = ctx.append_instruction("store", [arg_1])  # type: ignore
        symbols[sym.value] = new_var

    elif ir.value == "calldatacopy":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols, variables, allocated_variables)

        new_v = arg_0
        var = (
            _get_variable_from_address(variables, int(arg_0.value))
            if isinstance(arg_0, IRLiteral)
            else None
        )
        if var is not None:
            if allocated_variables.get(var.name, None) is None:
                new_v = ctx.append_instruction(
                    "alloca", [IRLiteral(var.size), IRLiteral(var.pos)]  # type: ignore
                )
                allocated_variables[var.name] = new_v  # type: ignore
            ctx.append_instruction("calldatacopy", [size, arg_1, new_v], False)  # type: ignore
            symbols[f"&{var.pos}"] = new_v  # type: ignore
        else:
            ctx.append_instruction("calldatacopy", [size, arg_1, new_v], False)  # type: ignore

        return new_v
    elif ir.value == "codecopy":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols, variables, allocated_variables)

        ctx.append_instruction("codecopy", [size, arg_1, arg_0], False)  # type: ignore
    elif ir.value == "symbol":
        return IRLabel(ir.args[0].value, True)
    elif ir.value == "data":
        label = IRLabel(ir.args[0].value)
        ctx.append_data("dbname", [label])
        for c in ir.args[1:]:
            if isinstance(c, int):
                assert 0 <= c <= 255, "data with invalid size"
                ctx.append_data("db", [c])  # type: ignore
            elif isinstance(c, bytes):
                ctx.append_data("db", [c])  # type: ignore
            elif isinstance(c, IRnode):
                data = _convert_ir_basicblock(ctx, c, symbols, variables, allocated_variables)
                ctx.append_data("db", [data])  # type: ignore
    elif ir.value == "assert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        current_bb = ctx.get_basic_block()
        inst = IRInstruction("assert", [arg_0])  # type: ignore
        current_bb.append_instruction(inst)
    elif ir.value == "label":
        label = IRLabel(ir.args[0].value, True)
        if not ctx.get_basic_block().is_terminated:
            inst = IRInstruction("jmp", [label])
            ctx.get_basic_block().append_instruction(inst)
        bb = IRBasicBlock(label, ctx)
        ctx.append_basic_block(bb)
        _convert_ir_basicblock(ctx, ir.args[2], symbols, variables, allocated_variables)
    elif ir.value == "exit_to":
        func_t = ir.passthrough_metadata.get("func_t", None)
        assert func_t is not None, "exit_to without func_t"

        if func_t.is_external:
            # Hardcoded contructor special case
            if func_t.name == "__init__":
                label = IRLabel(ir.args[0].value, True)
                inst = IRInstruction("jmp", [label])
                ctx.get_basic_block().append_instruction(inst)
                return None
            if func_t.return_type is None:
                inst = IRInstruction("stop", [])
                ctx.get_basic_block().append_instruction(inst)
                return None
            else:
                last_ir = None
                ret_var = ir.args[1]
                deleted = None
                if ret_var.is_literal and symbols.get(f"&{ret_var.value}", None) is not None:
                    deleted = symbols[f"&{ret_var.value}"]
                    del symbols[f"&{ret_var.value}"]
                for arg in ir.args[2:]:
                    last_ir = _convert_ir_basicblock(
                        ctx, arg, symbols, variables, allocated_variables
                    )
                if deleted is not None:
                    symbols[f"&{ret_var.value}"] = deleted

                ret_ir = _convert_ir_basicblock(
                    ctx, ret_var, symbols, variables, allocated_variables
                )

                var = (
                    _get_variable_from_address(variables, int(ret_ir.value))
                    if isinstance(ret_ir, IRLiteral)
                    else None
                )
                if var is not None:
                    allocated_var = allocated_variables.get(var.name, None)
                    assert allocated_var is not None, "unallocated variable"
                    new_var = symbols.get(f"&{ret_ir.value}", allocated_var)  # type: ignore

                    if var.size and int(var.size) > 32:
                        offset = int(ret_ir.value) - var.pos  # type: ignore
                        if offset > 0:
                            ptr_var = ctx.append_instruction(
                                "add", [IRLiteral(var.pos), IRLiteral(offset)]
                            )
                        else:
                            ptr_var = allocated_var
                        inst = IRInstruction("return", [last_ir, ptr_var])
                    else:
                        inst = _get_return_for_stack_operand(ctx, symbols, new_var, last_ir)
                else:
                    if isinstance(ret_ir, IRLiteral):
                        sym = symbols.get(f"&{ret_ir.value}", None)
                        if sym is None:
                            inst = IRInstruction("return", [last_ir, ret_ir])
                        else:
                            if func_t.return_type.memory_bytes_required > 32:
                                new_var = ctx.append_instruction("alloca", [IRLiteral(32), ret_ir])
                                ctx.append_instruction("mstore", [sym, new_var], False)
                                inst = IRInstruction("return", [last_ir, new_var])
                            else:
                                inst = IRInstruction("return", [last_ir, ret_ir])
                    else:
                        if last_ir and int(last_ir.value) > 32:
                            inst = IRInstruction("return", [last_ir, ret_ir])
                        else:
                            ret_buf = IRLiteral(128)  # TODO: need allocator
                            new_var = ctx.append_instruction("alloca", [IRLiteral(32), ret_buf])
                            ctx.append_instruction("mstore", [ret_ir, new_var], False)
                            inst = IRInstruction("return", [last_ir, new_var])

                ctx.get_basic_block().append_instruction(inst)
                ctx.append_basic_block(IRBasicBlock(ctx.get_next_label(), ctx))

        if func_t.is_internal:
            assert ir.args[1].value == "return_pc", "return_pc not found"
            if func_t.return_type is None:
                inst = IRInstruction("ret", [symbols["return_pc"]])
            else:
                if func_t.return_type.memory_bytes_required > 32:
                    inst = IRInstruction("ret", [symbols["return_buffer"], symbols["return_pc"]])
                else:
                    ret_by_value = ctx.append_instruction("mload", [symbols["return_buffer"]])
                    inst = IRInstruction("ret", [ret_by_value, symbols["return_pc"]])

            ctx.get_basic_block().append_instruction(inst)

    elif ir.value == "revert":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        inst = IRInstruction("revert", [arg_1, arg_0])
        ctx.get_basic_block().append_instruction(inst)

    elif ir.value == "dload":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        src = ctx.append_instruction("add", [arg_0, IRLabel("code_end")])

        ctx.append_instruction(
            "dloadbytes", [IRLiteral(32), src, IRLiteral(MemoryPositions.FREE_VAR_SPACE)], False
        )
        return ctx.append_instruction("mload", [IRLiteral(MemoryPositions.FREE_VAR_SPACE)])
    elif ir.value == "dloadbytes":
        dst = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        src_offset = _convert_ir_basicblock(
            ctx, ir.args[1], symbols, variables, allocated_variables
        )
        len_ = _convert_ir_basicblock(ctx, ir.args[2], symbols, variables, allocated_variables)

        src = ctx.append_instruction("add", [src_offset, IRLabel("code_end")])

        inst = IRInstruction("dloadbytes", [len_, src, dst])
        ctx.get_basic_block().append_instruction(inst)
        return None
    elif ir.value == "mload":
        sym_ir = ir.args[0]
        var = (
            _get_variable_from_address(variables, int(sym_ir.value)) if sym_ir.is_literal else None
        )
        if var is not None:
            if var.size and var.size > 32:
                if allocated_variables.get(var.name, None) is None:
                    allocated_variables[var.name] = ctx.append_instruction(
                        "alloca", [IRLiteral(var.size), IRLiteral(var.pos)]
                    )

                offset = int(sym_ir.value) - var.pos
                if offset > 0:
                    ptr_var = ctx.append_instruction("add", [IRLiteral(var.pos), IRLiteral(offset)])
                else:
                    ptr_var = allocated_variables[var.name]

                return ctx.append_instruction("mload", [ptr_var])
            else:
                if sym_ir.is_literal:
                    sym = symbols.get(f"&{sym_ir.value}", None)
                    if sym is None:
                        new_var = ctx.append_instruction("store", [sym_ir])
                        symbols[f"&{sym_ir.value}"] = new_var
                        if allocated_variables.get(var.name, None) is None:
                            allocated_variables[var.name] = new_var
                            return new_var
                    else:
                        return sym

                sym = symbols.get(f"&{sym_ir.value}", None)
                assert sym is not None, "unallocated variable"
                return sym
        else:
            if sym_ir.is_literal:
                new_var = symbols.get(f"&{sym_ir.value}", None)
                if new_var is not None:
                    return ctx.append_instruction("mload", [new_var])
                else:
                    return ctx.append_instruction("mload", [IRLiteral(sym_ir.value)])
            else:
                new_var = _convert_ir_basicblock(
                    ctx, sym_ir, symbols, variables, allocated_variables
                )
                #
                # Old IR gets it's return value as a reference in the stack
                # New IR gets it's return value in stack in case of 32 bytes or less
                # So here we detect ahead of time if this mload leads a self call and
                # and we skip the mload
                #
                if sym_ir.is_self_call:
                    return new_var
                return ctx.append_instruction("mload", [new_var])

    elif ir.value == "mstore":
        sym_ir = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)

        var = None
        if isinstance(sym_ir, IRLiteral):
            var = _get_variable_from_address(variables, int(sym_ir.value))

        if var is not None and var.size is not None:
            if var.size and var.size > 32:
                if allocated_variables.get(var.name, None) is None:
                    allocated_variables[var.name] = ctx.append_instruction(
                        "alloca", [IRLiteral(var.size), IRLiteral(var.pos)]
                    )

                offset = int(sym_ir.value) - var.pos
                if offset > 0:
                    ptr_var = ctx.append_instruction("add", [IRLiteral(var.pos), IRLiteral(offset)])
                else:
                    ptr_var = allocated_variables[var.name]

                return ctx.append_instruction("mstore", [arg_1, ptr_var], False)
            else:
                if isinstance(sym_ir, IRLiteral):
                    new_var = ctx.append_instruction("store", [arg_1])
                    symbols[f"&{sym_ir.value}"] = new_var
                    # if allocated_variables.get(var.name, None) is None:
                    allocated_variables[var.name] = new_var
                return new_var
        else:
            if not isinstance(sym_ir, IRLiteral):
                inst = IRInstruction("mstore", [arg_1, sym_ir])
                ctx.get_basic_block().append_instruction(inst)
                return None

            sym = symbols.get(f"&{sym_ir.value}", None)
            if sym is None:
                inst = IRInstruction("mstore", [arg_1, sym_ir])
                ctx.get_basic_block().append_instruction(inst)
                if arg_1 and not isinstance(sym_ir, IRLiteral):
                    symbols[f"&{sym_ir.value}"] = arg_1
                return None

            if isinstance(sym_ir, IRLiteral):
                inst = IRInstruction("mstore", [arg_1, sym])
                ctx.get_basic_block().append_instruction(inst)
                return None
            else:
                symbols[sym_ir.value] = arg_1
                return arg_1

    elif ir.value in ["sload", "iload"]:
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        return ctx.append_instruction(ir.value, [arg_0])
    elif ir.value in ["sstore", "istore"]:
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        inst = IRInstruction(ir.value, [arg_1, arg_0])
        ctx.get_basic_block().append_instruction(inst)
    elif ir.value == "unique_symbol":
        sym = ir.args[0]
        new_var = ctx.get_next_variable()
        symbols[f"&{sym.value}"] = new_var
        return new_var
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
        def emit_body_block():
            global _break_target, _continue_target
            old_targets = _break_target, _continue_target
            _break_target, _continue_target = exit_block, increment_block
            _convert_ir_basicblock(ctx, body, symbols, variables, allocated_variables)
            _break_target, _continue_target = old_targets

        sym = ir.args[0]
        start = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        end = _convert_ir_basicblock(ctx, ir.args[2], symbols, variables, allocated_variables)
        # "bound" is not used
        _ = _convert_ir_basicblock(ctx, ir.args[3], symbols, variables, allocated_variables)
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

        inst = IRInstruction("store", [start], counter_var)
        ctx.get_basic_block().append_instruction(inst)
        symbols[sym.value] = counter_var
        inst = IRInstruction("jmp", [cond_block.label])
        ctx.get_basic_block().append_instruction(inst)

        symbols[sym.value] = ret
        cond_block.append_instruction(
            IRInstruction(
                "phi", [entry_block.label, counter_var, increment_block.label, counter_inc_var], ret
            )
        )

        xor_ret = ctx.get_next_variable()
        cont_ret = ctx.get_next_variable()
        inst = IRInstruction("xor", [ret, end], xor_ret)
        cond_block.append_instruction(inst)
        cond_block.append_instruction(IRInstruction("iszero", [xor_ret], cont_ret))
        ctx.append_basic_block(cond_block)

        # Do a dry run to get the symbols needing phi nodes
        start_syms = symbols.copy()
        ctx.append_basic_block(body_block)
        emit_body_block()
        end_syms = symbols.copy()
        diff_syms = _get_symbols_common(start_syms, end_syms)

        replacements = {}
        for sym, val in diff_syms.items():
            new_var = ctx.get_next_variable()
            symbols[sym] = new_var
            replacements[val[0]] = new_var
            replacements[val[1]] = new_var
            cond_block.insert_instruction(
                IRInstruction(
                    "phi", [entry_block.label, val[0], increment_block.label, val[1]], new_var
                ),
                1,
            )

        body_block.replace_operands(replacements)

        body_end = ctx.get_basic_block()
        if not body_end.is_terminated:
            body_end.append_instruction(IRInstruction("jmp", [jump_up_block.label]))

        jump_cond = IRInstruction("jmp", [increment_block.label])
        jump_up_block.append_instruction(jump_cond)
        ctx.append_basic_block(jump_up_block)

        increment_block.append_instruction(
            IRInstruction("add", [ret, IRLiteral(1)], counter_inc_var)
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
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        arg_1 = _convert_ir_basicblock(ctx, ir.args[1], symbols, variables, allocated_variables)
        size = _convert_ir_basicblock(ctx, ir.args[2], symbols, variables, allocated_variables)

        new_var = ctx.append_instruction("returndatacopy", [arg_1, size])

        symbols[f"&{arg_0.value}"] = new_var
        return new_var
    elif ir.value == "selfdestruct":
        arg_0 = _convert_ir_basicblock(ctx, ir.args[0], symbols, variables, allocated_variables)
        ctx.append_instruction("selfdestruct", [arg_0], False)
    elif isinstance(ir.value, str) and (
        ir.value.startswith("log") or ir.value.startswith("shadow")
    ):
        args = [
            _convert_ir_basicblock(ctx, arg, symbols, variables, allocated_variables)
            for arg in ir.args
        ]
        inst = IRInstruction(ir.value, reversed(args))
        ctx.get_basic_block().append_instruction(inst)
    elif isinstance(ir.value, str) and ir.value.upper() in get_opcodes():
        _convert_ir_opcode(ctx, ir, symbols, variables, allocated_variables)
    elif isinstance(ir.value, str) and ir.value in symbols:
        return symbols[ir.value]
    elif ir.is_literal:
        return IRLiteral(ir.value)
    else:
        raise Exception(f"Unknown IR node: {ir}")

    return None


def _convert_ir_opcode(
    ctx: IRFunction,
    ir: IRnode,
    symbols: SymbolTable,
    variables: OrderedSet,
    allocated_variables: dict[str, IRVariable],
) -> None:
    opcode = ir.value.upper()  # type: ignore
    inst_args = []
    for arg in ir.args:
        if isinstance(arg, IRnode):
            inst_args.append(
                _convert_ir_basicblock(ctx, arg, symbols, variables, allocated_variables)
            )
    instruction = IRInstruction(opcode, inst_args)  # type: ignore
    ctx.get_basic_block().append_instruction(instruction)


def _data_ofst_of(sym, ofst, height_):
    # e.g. _OFST _sym_foo 32
    assert is_symbol(sym) or is_mem_sym(sym)
    if isinstance(ofst.value, int):
        # resolve at compile time using magic _OFST op
        return ["_OFST", sym, ofst.value]
    else:
        # if we can't resolve at compile time, resolve at runtime
        # ofst = _compile_to_assembly(ofst, withargs, existing_labels, break_dest, height_)
        return ofst + [sym, "ADD"]
