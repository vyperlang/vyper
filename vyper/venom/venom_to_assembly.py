from typing import Any

from vyper.exceptions import CompilerPanic, StackTooDeep
from vyper.ir.compile_ir import (
    PUSH,
    DataHeader,
    Instruction,
    RuntimeHeader,
    mksymbol,
    optimize_assembly,
)
from vyper.utils import MemoryPositions, OrderedSet, wrap256
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysesCache, LivenessAnalysis
from vyper.venom.basicblock import (
    TEST_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRContext
from vyper.venom.passes import NormalizationPass
from vyper.venom.stack_model import StackModel

DEBUG_SHOW_COST = False
if DEBUG_SHOW_COST:
    import sys

# instructions which map one-to-one from venom to EVM
_ONE_TO_ONE_INSTRUCTIONS = frozenset(
    [
        "revert",
        "coinbase",
        "calldatasize",
        "calldatacopy",
        "mcopy",
        "calldataload",
        "codecopy",
        "gas",
        "gasprice",
        "gaslimit",
        "chainid",
        "address",
        "origin",
        "number",
        "extcodesize",
        "extcodehash",
        "extcodecopy",
        "returndatasize",
        "returndatacopy",
        "callvalue",
        "selfbalance",
        "sload",
        "sstore",
        "mload",
        "mstore",
        "tload",
        "tstore",
        "timestamp",
        "caller",
        "blockhash",
        "selfdestruct",
        "signextend",
        "stop",
        "shr",
        "shl",
        "sar",
        "and",
        "xor",
        "or",
        "add",
        "sub",
        "mul",
        "div",
        "smul",
        "sdiv",
        "mod",
        "smod",
        "exp",
        "addmod",
        "mulmod",
        "eq",
        "iszero",
        "not",
        "lt",
        "gt",
        "slt",
        "sgt",
        "create",
        "create2",
        "msize",
        "balance",
        "call",
        "staticcall",
        "delegatecall",
        "codesize",
        "basefee",
        "blobhash",
        "blobbasefee",
        "prevrandao",
        "difficulty",
        "invalid",
    ]
)

_REVERT_POSTAMBLE = ["_sym___revert", "JUMPDEST", *PUSH(0), "DUP1", "REVERT"]


def apply_line_numbers(inst: IRInstruction, asm) -> list[str]:
    ret = []
    for op in asm:
        if isinstance(op, str) and not isinstance(op, Instruction):
            ret.append(Instruction(op, inst.ast_source, inst.error_msg))
        else:
            ret.append(op)
    return ret  # type: ignore


def _as_asm_symbol(label: IRLabel) -> str:
    # Lower an IRLabel to an assembly symbol
    return f"_sym_{label.value}"


# TODO: "assembly" gets into the recursion due to how the original
# IR was structured recursively in regards with the deploy instruction.
# There, recursing into the deploy instruction was by design, and
# made it easier to make the assembly generated "recursive" (i.e.
# instructions being lists of instructions). We don't have this restriction
# anymore, so we can probably refactor this to be iterative in coordination
# with the assembler. My suggestion is to let this be for now, and we can
# refactor it later when we are finished phasing out the old IR.
class VenomCompiler:
    ctxs: list[IRContext]
    label_counter = 0
    visited_instructions: OrderedSet  # {IRInstruction}
    visited_basicblocks: OrderedSet  # {IRBasicBlock}
    liveness_analysis: LivenessAnalysis
    dfg: DFGAnalysis

    def __init__(self, ctxs: list[IRContext]):
        self.ctxs = ctxs
        self.label_counter = 0
        self.visited_instructions = OrderedSet()
        self.visited_basicblocks = OrderedSet()

    def generate_evm(self, no_optimize: bool = False) -> list[str]:
        self.visited_instructions = OrderedSet()
        self.visited_basicblocks = OrderedSet()
        self.label_counter = 0

        asm: list[Any] = []
        top_asm = asm

        for ctx in self.ctxs:
            for fn in ctx.functions.values():
                ac = IRAnalysesCache(fn)

                NormalizationPass(ac, fn).run_pass()
                self.liveness_analysis = ac.request_analysis(LivenessAnalysis)
                self.dfg = ac.request_analysis(DFGAnalysis)
                ac.request_analysis(CFGAnalysis)

                assert fn.normalized, "Non-normalized CFG!"

                self._generate_evm_for_basicblock_r(asm, fn.entry, StackModel())

            # TODO make this property on IRFunction
            asm.extend(["_sym__ctor_exit", "JUMPDEST"])
            if ctx.immutables_len is not None and ctx.ctor_mem_size is not None:
                asm.extend(
                    ["_sym_subcode_size", "_sym_runtime_begin", "_mem_deploy_start", "CODECOPY"]
                )
                asm.extend(["_OFST", "_sym_subcode_size", ctx.immutables_len])  # stack: len
                asm.extend(["_mem_deploy_start"])  # stack: len mem_ofst
                asm.extend(["RETURN"])
                asm.extend(_REVERT_POSTAMBLE)
                runtime_asm = [
                    RuntimeHeader("_sym_runtime_begin", ctx.ctor_mem_size, ctx.immutables_len)
                ]
                asm.append(runtime_asm)
                asm = runtime_asm
            else:
                asm.extend(_REVERT_POSTAMBLE)

            # Append data segment
            for data_section in ctx.data_segment:
                label = data_section.label
                asm_data_section: list[Any] = []
                asm_data_section.append(DataHeader(_as_asm_symbol(label)))
                for item in data_section.data_items:
                    data = item.data
                    if isinstance(data, IRLabel):
                        asm_data_section.append(_as_asm_symbol(data))
                    else:
                        assert isinstance(data, bytes)
                        asm_data_section.append(data)

                asm.append(asm_data_section)

        if no_optimize is False:
            optimize_assembly(top_asm)

        return top_asm

    def _stack_reorder(
        self, assembly: list, stack: StackModel, stack_ops: list[IROperand], dry_run: bool = False
    ) -> int:
        if dry_run:
            assert len(assembly) == 0, "Dry run should not work on assembly"
            stack = stack.copy()

        if len(stack_ops) == 0:
            return 0

        assert len(stack_ops) == len(set(stack_ops))  # precondition

        cost = 0
        for i, op in enumerate(stack_ops):
            final_stack_depth = -(len(stack_ops) - i - 1)
            depth = stack.get_depth(op)

            if depth == StackModel.NOT_IN_STACK:
                raise CompilerPanic(f"Variable {op} not in stack")

            if depth == final_stack_depth:
                continue

            to_swap = stack.peek(final_stack_depth)
            if self.dfg.are_equivalent(op, to_swap):
                # perform a "virtual" swap
                stack.poke(final_stack_depth, op)
                stack.poke(depth, to_swap)
                continue

            cost += self.swap(assembly, stack, depth)
            cost += self.swap(assembly, stack, final_stack_depth)

        assert stack._stack[-len(stack_ops) :] == stack_ops, (stack, stack_ops)

        return cost

    def _emit_input_operands(
        self,
        assembly: list,
        inst: IRInstruction,
        ops: list[IROperand],
        stack: StackModel,
        next_liveness: OrderedSet[IRVariable],
    ) -> None:
        # PRE: we already have all the items on the stack that have
        # been scheduled to be killed. now it's just a matter of emitting
        # SWAPs, DUPs and PUSHes until we match the `ops` argument

        # to validate store expansion invariant -
        # each op is emitted at most once.
        seen: set[IROperand] = set()

        for op in ops:
            if isinstance(op, IRLabel):
                # invoke emits the actual instruction itself so we don't need
                # to emit it here but we need to add it to the stack map
                if inst.opcode != "invoke":
                    assembly.append(_as_asm_symbol(op))
                stack.push(op)
                continue

            if isinstance(op, IRLiteral):
                if op.value < -(2**255):
                    raise Exception(f"Value too low: {op.value}")
                elif op.value >= 2**256:
                    raise Exception(f"Value too high: {op.value}")
                assembly.extend(PUSH(wrap256(op.value)))
                stack.push(op)
                continue

            if op in next_liveness:
                self.dup_op(assembly, stack, op)

            # guaranteed by store expansion
            assert op not in seen, (op, seen)
            seen.add(op)

    def _generate_evm_for_basicblock_r(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        if basicblock in self.visited_basicblocks:
            return
        self.visited_basicblocks.add(basicblock)

        if DEBUG_SHOW_COST:
            print(basicblock, file=sys.stderr)

        ref = asm
        asm = []

        # assembly entry point into the block
        asm.append(_as_asm_symbol(basicblock.label))
        asm.append("JUMPDEST")

        if len(basicblock.cfg_in) == 1:
            self.clean_stack_from_cfg_in(asm, basicblock, stack)

        all_insts = sorted(basicblock.instructions, key=lambda x: x.opcode != "param")

        for i, inst in enumerate(all_insts):
            next_liveness = (
                all_insts[i + 1].liveness if i + 1 < len(all_insts) else basicblock.out_vars
            )

            asm.extend(self._generate_evm_for_instruction(inst, stack, next_liveness))

        if DEBUG_SHOW_COST:
            print(" ".join(map(str, asm)), file=sys.stderr)
            print("\n", file=sys.stderr)

        ref.extend(asm)

        for bb in basicblock.cfg_out:
            self._generate_evm_for_basicblock_r(ref, bb, stack.copy())

    # pop values from stack at entry to bb
    # note this produces the same result(!) no matter which basic block
    # we enter from in the CFG.
    def clean_stack_from_cfg_in(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        # the input block is a splitter block, like jnz or djmp
        assert len(basicblock.cfg_in) == 1
        in_bb = basicblock.cfg_in.first()
        assert len(in_bb.cfg_out) > 1

        # inputs is the input variables we need from in_bb
        inputs = self.liveness_analysis.input_vars_from(in_bb, basicblock)

        # layout is the output stack layout for in_bb (which works
        # for all possible cfg_outs from the in_bb, in_bb is responsible
        # for making sure its output stack layout works no matter which
        # bb it jumps into).
        layout = in_bb.out_vars
        to_pop = list(layout.difference(inputs))

        # small heuristic: pop from shallowest first.
        to_pop.sort(key=lambda var: -stack.get_depth(var))

        # NOTE: we could get more fancy and try to optimize the swap
        # operations here, there is probably some more room for optimization.
        for var in to_pop:
            depth = stack.get_depth(var)

            if depth != 0:
                self.swap(asm, stack, depth)
            self.pop(asm, stack)

    def _generate_evm_for_instruction(
        self, inst: IRInstruction, stack: StackModel, next_liveness: OrderedSet
    ) -> list[str]:
        assembly: list[str | int] = []
        opcode = inst.opcode

        #
        # generate EVM for op
        #

        # Step 1: Apply instruction special stack manipulations

        if opcode in ["jmp", "djmp", "jnz", "invoke"]:
            operands = list(inst.get_non_label_operands())
        elif opcode in ("alloca", "palloca"):
            assert len(inst.operands) == 3, f"alloca/palloca must have 3 operands, got {inst}"
            offset, _size, _id = inst.operands
            operands = [offset]

        # iload and istore are special cases because they can take a literal
        # that is handled specialy with the _OFST macro. Look below, after the
        # stack reordering.
        elif opcode == "iload":
            addr = inst.operands[0]
            if isinstance(addr, IRLiteral):
                operands = []
            else:
                operands = inst.operands
        elif opcode == "istore":
            addr = inst.operands[1]
            if isinstance(addr, IRLiteral):
                operands = inst.operands[:1]
            else:
                operands = inst.operands
        elif opcode == "log":
            log_topic_count = inst.operands[0].value
            assert log_topic_count in [0, 1, 2, 3, 4], "Invalid topic count"
            operands = inst.operands[1:]
        else:
            operands = inst.operands

        if opcode == "phi":
            ret = inst.get_outputs()[0]
            phis = list(inst.get_input_variables())
            depth = stack.get_phi_depth(phis)
            # collapse the arguments to the phi node in the stack.
            # example, for `%56 = %label1 %13 %label2 %14`, we will
            # find an instance of %13 *or* %14 in the stack and replace it with %56.
            to_be_replaced = stack.peek(depth)
            if to_be_replaced in next_liveness:
                # this branch seems unreachable (maybe due to make_ssa)
                # %13/%14 is still live(!), so we make a copy of it
                self.dup(assembly, stack, depth)
                stack.poke(0, ret)
            else:
                stack.poke(depth, ret)
            return apply_line_numbers(inst, assembly)

        if opcode == "offset":
            ofst, label = inst.operands
            assert isinstance(label, IRLabel)  # help mypy
            assembly.extend(["_OFST", _as_asm_symbol(label), ofst.value])
            assert isinstance(inst.output, IROperand), "Offset must have output"
            stack.push(inst.output)
            return apply_line_numbers(inst, assembly)

        # Step 2: Emit instruction's input operands
        self._emit_input_operands(assembly, inst, operands, stack, next_liveness)

        # Step 3: Reorder stack before join points
        if opcode == "jmp":
            # prepare stack for jump into a join point
            # we only need to reorder stack before join points, which after
            # cfg normalization, join points can only be led into by
            # jmp instructions.
            assert isinstance(inst.parent.cfg_out, OrderedSet)
            assert len(inst.parent.cfg_out) == 1
            next_bb = inst.parent.cfg_out.first()

            # guaranteed by cfg normalization+simplification
            assert len(next_bb.cfg_in) > 1

            target_stack = self.liveness_analysis.input_vars_from(inst.parent, next_bb)
            # NOTE: in general the stack can contain multiple copies of
            # the same variable, however, before a jump that is not possible
            self._stack_reorder(assembly, stack, list(target_stack))

        if inst.is_commutative:
            cost_no_swap = self._stack_reorder([], stack, operands, dry_run=True)
            operands[-1], operands[-2] = operands[-2], operands[-1]
            cost_with_swap = self._stack_reorder([], stack, operands, dry_run=True)
            if cost_with_swap > cost_no_swap:
                operands[-1], operands[-2] = operands[-2], operands[-1]

        cost = self._stack_reorder([], stack, operands, dry_run=True)
        if DEBUG_SHOW_COST and cost:
            print("ENTER", inst, file=sys.stderr)
            print("  HAVE", stack, file=sys.stderr)
            print("  WANT", operands, file=sys.stderr)
            print("  COST", cost, file=sys.stderr)

        # final step to get the inputs to this instruction ordered
        # correctly on the stack
        self._stack_reorder(assembly, stack, operands)

        # some instructions (i.e. invoke) need to do stack manipulations
        # with the stack model containing the return value(s), so we fiddle
        # with the stack model beforehand.

        # Step 4: Push instruction's return value to stack
        stack.pop(len(operands))
        if inst.output is not None:
            stack.push(inst.output)

        # Step 5: Emit the EVM instruction(s)
        if opcode in _ONE_TO_ONE_INSTRUCTIONS:
            assembly.append(opcode.upper())
        elif opcode in ("alloca", "palloca"):
            pass
        elif opcode == "param":
            pass
        elif opcode == "store":
            pass
        elif opcode in ["codecopy", "dloadbytes"]:
            assembly.append("CODECOPY")
        elif opcode == "dbname":
            pass
        elif opcode == "jnz":
            # jump if not zero
            if_nonzero_label, if_zero_label = inst.get_label_operands()
            assembly.append(_as_asm_symbol(if_nonzero_label))
            assembly.append("JUMPI")

            # make sure the if_zero_label will be optimized out
            # assert if_zero_label == next(iter(inst.parent.cfg_out)).label

            assembly.append(_as_asm_symbol(if_zero_label))
            assembly.append("JUMP")

        elif opcode == "jmp":
            (target,) = inst.operands
            assert isinstance(target, IRLabel)
            assembly.append(_as_asm_symbol(target))
            assembly.append("JUMP")
        elif opcode == "djmp":
            assert isinstance(
                inst.operands[0], IRVariable
            ), f"Expected IRVariable, got {inst.operands[0]}"
            assembly.append("JUMP")
        elif opcode == "invoke":
            target = inst.operands[0]
            assert isinstance(
                target, IRLabel
            ), f"invoke target must be a label (is ${type(target)} ${target})"
            assembly.extend(
                [
                    f"_sym_label_ret_{self.label_counter}",
                    _as_asm_symbol(target),
                    "JUMP",
                    f"_sym_label_ret_{self.label_counter}",
                    "JUMPDEST",
                ]
            )
            self.label_counter += 1
        elif opcode == "ret":
            assembly.append("JUMP")
        elif opcode == "return":
            assembly.append("RETURN")
        elif opcode == "exit":
            assembly.extend(["_sym__ctor_exit", "JUMP"])
        elif opcode == "phi":
            pass
        elif opcode == "sha3":
            assembly.append("SHA3")
        elif opcode == "sha3_64":
            assembly.extend(
                [
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "MSTORE",
                    *PUSH(MemoryPositions.FREE_VAR_SPACE2),
                    "MSTORE",
                    *PUSH(64),
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "SHA3",
                ]
            )
        elif opcode == "assert":
            assembly.extend(["ISZERO", "_sym___revert", "JUMPI"])
        elif opcode == "assert_unreachable":
            end_symbol = mksymbol("reachable")
            assembly.extend([end_symbol, "JUMPI", "INVALID", end_symbol, "JUMPDEST"])
        elif opcode == "iload":
            addr = inst.operands[0]
            if isinstance(addr, IRLiteral):
                assembly.extend(["_OFST", "_mem_deploy_end", addr.value])
            else:
                assembly.extend(["_mem_deploy_end", "ADD"])
            assembly.append("MLOAD")
        elif opcode == "istore":
            addr = inst.operands[1]
            if isinstance(addr, IRLiteral):
                assembly.extend(["_OFST", "_mem_deploy_end", addr.value])
            else:
                assembly.extend(["_mem_deploy_end", "ADD"])
            assembly.append("MSTORE")
        elif opcode == "log":
            assembly.extend([f"LOG{log_topic_count}"])
        elif opcode == "nop":
            pass
        elif opcode in TEST_INSTRUCTIONS:
            raise CompilerPanic(f"Bad instruction: {opcode}")
        else:
            raise Exception(f"Unknown opcode: {opcode}")

        # Step 6: Emit instructions output operands (if any)
        if inst.output is not None:
            if inst.output not in next_liveness:
                self.pop(assembly, stack)
            else:
                # heuristic: peek at next_liveness to find the next scheduled
                # item, and optimistically swap with it
                if DEBUG_SHOW_COST:
                    stack0 = stack.copy()

                next_scheduled = next_liveness.last()
                cost = 0
                if not self.dfg.are_equivalent(inst.output, next_scheduled):
                    cost = self.swap_op(assembly, stack, next_scheduled)

                if DEBUG_SHOW_COST and cost != 0:
                    print("ENTER", inst, file=sys.stderr)
                    print("  HAVE", stack0, file=sys.stderr)
                    print("  NEXT LIVENESS", next_liveness, file=sys.stderr)
                    print("  NEW_STACK", stack, file=sys.stderr)

        return apply_line_numbers(inst, assembly)

    def pop(self, assembly, stack, num=1):
        stack.pop(num)
        assembly.extend(["POP"] * num)

    def swap(self, assembly, stack, depth) -> int:
        # Swaps of the top is no op
        if depth == 0:
            return 0

        stack.swap(depth)
        assembly.append(_evm_swap_for(depth))
        return 1

    def dup(self, assembly, stack, depth):
        stack.dup(depth)
        assembly.append(_evm_dup_for(depth))

    def swap_op(self, assembly, stack, op):
        depth = stack.get_depth(op)
        assert depth is not StackModel.NOT_IN_STACK, f"Cannot swap non-existent operand {op}"
        return self.swap(assembly, stack, depth)

    def dup_op(self, assembly, stack, op):
        depth = stack.get_depth(op)
        assert depth is not StackModel.NOT_IN_STACK, f"Cannot dup non-existent operand {op}"
        self.dup(assembly, stack, depth)


def _evm_swap_for(depth: int) -> str:
    swap_idx = -depth
    if not (1 <= swap_idx <= 16):
        raise StackTooDeep(f"Unsupported swap depth {swap_idx}")
    return f"SWAP{swap_idx}"


def _evm_dup_for(depth: int) -> str:
    dup_idx = 1 - depth
    if not (1 <= dup_idx <= 16):
        raise StackTooDeep(f"Unsupported dup depth {dup_idx}")
    return f"DUP{dup_idx}"
