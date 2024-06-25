from collections import Counter
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
from vyper.utils import MemoryPositions, OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dup_requirements import DupRequirementsAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRContext
from vyper.venom.passes.normalization import NormalizationPass
from vyper.venom.stack_model import StackModel

# instructions which map one-to-one from venom to EVM
_ONE_TO_ONE_INSTRUCTIONS = frozenset(
    [
        "revert",
        "coinbase",
        "calldatasize",
        "calldatacopy",
        "mcopy",
        "calldataload",
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

COMMUTATIVE_INSTRUCTIONS = frozenset(["add", "mul", "smul", "or", "xor", "and", "eq"])


_REVERT_POSTAMBLE = ["_sym___revert", "JUMPDEST", *PUSH(0), "DUP1", "REVERT"]


def apply_line_numbers(inst: IRInstruction, asm) -> list[str]:
    ret = []
    for op in asm:
        if isinstance(op, str) and not isinstance(op, Instruction):
            ret.append(Instruction(op, inst.ast_source, inst.error_msg))
        else:
            ret.append(op)
    return ret  # type: ignore


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
                ac.request_analysis(DupRequirementsAnalysis)

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
            data_segments: dict = dict()
            for inst in ctx.data_segment:
                if inst.opcode == "dbname":
                    label = inst.operands[0].value
                    data_segments[label] = [DataHeader(f"_sym_{label}")]
                elif inst.opcode == "db":
                    data = inst.operands[0]
                    if isinstance(data, IRLabel):
                        data_segments[label].append(f"_sym_{data.value}")
                    else:
                        data_segments[label].append(data)

            asm.extend(list(data_segments.values()))

        if no_optimize is False:
            optimize_assembly(top_asm)

        return top_asm

    def _stack_reorder(
        self, assembly: list, stack: StackModel, stack_ops: list[IROperand], dry_run: bool = False
    ) -> int:
        cost = 0

        if dry_run:
            assert len(assembly) == 0, "Dry run should not work on assembly"
            stack = stack.copy()

        stack_ops_count = len(stack_ops)

        counts = Counter(stack_ops)

        for i in range(stack_ops_count):
            op = stack_ops[i]
            final_stack_depth = -(stack_ops_count - i - 1)
            depth = stack.get_depth(op, counts[op])  # type: ignore
            counts[op] -= 1

            if depth == StackModel.NOT_IN_STACK:
                raise CompilerPanic(f"Variable {op} not in stack")

            if depth == final_stack_depth:
                continue

            if op == stack.peek(final_stack_depth):
                continue

            cost += self.swap(assembly, stack, depth)
            cost += self.swap(assembly, stack, final_stack_depth)

        return cost

    def _emit_input_operands(
        self, assembly: list, inst: IRInstruction, ops: list[IROperand], stack: StackModel
    ) -> None:
        # PRE: we already have all the items on the stack that have
        # been scheduled to be killed. now it's just a matter of emitting
        # SWAPs, DUPs and PUSHes until we match the `ops` argument

        # dumb heuristic: if the top of stack is not wanted here, swap
        # it with something that is wanted
        if ops and stack.height > 0 and stack.peek(0) not in ops:
            for op in ops:
                if isinstance(op, IRVariable) and op not in inst.dup_requirements:
                    self.swap_op(assembly, stack, op)
                    break

        emitted_ops = OrderedSet[IROperand]()
        for op in ops:
            if isinstance(op, IRLabel):
                # invoke emits the actual instruction itself so we don't need to emit it here
                # but we need to add it to the stack map
                if inst.opcode != "invoke":
                    assembly.append(f"_sym_{op.value}")
                stack.push(op)
                continue

            if isinstance(op, IRLiteral):
                if op.value < -(2**255):
                    raise Exception(f"Value too low: {op.value}")
                elif op.value >= 2**256:
                    raise Exception(f"Value too high: {op.value}")
                assembly.extend(PUSH(op.value % 2**256))
                stack.push(op)
                continue

            if op in inst.dup_requirements and op not in emitted_ops:
                self.dup_op(assembly, stack, op)

            if op in emitted_ops:
                self.dup_op(assembly, stack, op)

            emitted_ops.add(op)

    def _generate_evm_for_basicblock_r(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        if basicblock in self.visited_basicblocks:
            return
        self.visited_basicblocks.add(basicblock)

        # assembly entry point into the block
        asm.append(f"_sym_{basicblock.label}")
        asm.append("JUMPDEST")

        self.clean_stack_from_cfg_in(asm, basicblock, stack)

        param_insts = [inst for inst in basicblock.instructions if inst.opcode == "param"]
        main_insts = [inst for inst in basicblock.instructions if inst.opcode != "param"]

        for inst in param_insts:
            asm.extend(self._generate_evm_for_instruction(inst, stack))

        self._clean_unused_params(asm, basicblock, stack)

        for i, inst in enumerate(main_insts):
            next_liveness = main_insts[i + 1].liveness if i + 1 < len(main_insts) else OrderedSet()

            asm.extend(self._generate_evm_for_instruction(inst, stack, next_liveness))

        for bb in basicblock.reachable:
            self._generate_evm_for_basicblock_r(asm, bb, stack.copy())

    def _clean_unused_params(self, asm: list, bb: IRBasicBlock, stack: StackModel) -> None:
        for i, inst in enumerate(bb.instructions):
            if inst.opcode != "param":
                break
            if inst.is_volatile and i + 1 < len(bb.instructions):
                liveness = bb.instructions[i + 1].liveness
                if inst.output is not None and inst.output not in liveness:
                    depth = stack.get_depth(inst.output)
                    if depth != 0:
                        self.swap(asm, stack, depth)
                    self.pop(asm, stack)

    # pop values from stack at entry to bb
    # note this produces the same result(!) no matter which basic block
    # we enter from in the CFG.
    def clean_stack_from_cfg_in(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        if len(basicblock.cfg_in) == 0:
            return

        to_pop = OrderedSet[IRVariable]()
        for in_bb in basicblock.cfg_in:
            # inputs is the input variables we need from in_bb
            inputs = self.liveness_analysis.input_vars_from(in_bb, basicblock)

            # layout is the output stack layout for in_bb (which works
            # for all possible cfg_outs from the in_bb).
            layout = in_bb.out_vars

            # pop all the stack items which in_bb produced which we don't need.
            to_pop |= layout.difference(inputs)

        for var in to_pop:
            depth = stack.get_depth(var)
            # don't pop phantom phi inputs
            if depth is StackModel.NOT_IN_STACK:
                continue

            if depth != 0:
                self.swap(asm, stack, depth)
            self.pop(asm, stack)

    def _generate_evm_for_instruction(
        self, inst: IRInstruction, stack: StackModel, next_liveness: OrderedSet = None
    ) -> list[str]:
        assembly: list[str | int] = []
        next_liveness = next_liveness or OrderedSet()
        opcode = inst.opcode

        #
        # generate EVM for op
        #

        # Step 1: Apply instruction special stack manipulations

        if opcode in ["jmp", "djmp", "jnz", "invoke"]:
            operands = list(inst.get_non_label_operands())
        elif opcode == "alloca":
            offset, _size = inst.operands
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
            if to_be_replaced in inst.dup_requirements:
                # %13/%14 is still live(!), so we make a copy of it
                self.dup(assembly, stack, depth)
                stack.poke(0, ret)
            else:
                stack.poke(depth, ret)
            return apply_line_numbers(inst, assembly)

        # Step 2: Emit instruction's input operands
        self._emit_input_operands(assembly, inst, operands, stack)

        # Step 3: Reorder stack
        if opcode in ["jnz", "djmp", "jmp"]:
            # prepare stack for jump into another basic block
            assert inst.parent and isinstance(inst.parent.cfg_out, OrderedSet)
            b = next(iter(inst.parent.cfg_out))
            target_stack = self.liveness_analysis.input_vars_from(inst.parent, b)
            # TODO optimize stack reordering at entry and exit from basic blocks
            # NOTE: stack in general can contain multiple copies of the same variable,
            # however we are safe in the case of jmp/djmp/jnz as it's not going to
            # have multiples.
            target_stack_list = list(target_stack)
            self._stack_reorder(assembly, stack, target_stack_list)

        if opcode in COMMUTATIVE_INSTRUCTIONS:
            cost_no_swap = self._stack_reorder([], stack, operands, dry_run=True)
            operands[-1], operands[-2] = operands[-2], operands[-1]
            cost_with_swap = self._stack_reorder([], stack, operands, dry_run=True)
            if cost_with_swap > cost_no_swap:
                operands[-1], operands[-2] = operands[-2], operands[-1]

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
        elif opcode == "alloca":
            pass
        elif opcode == "param":
            pass
        elif opcode == "store":
            pass
        elif opcode == "dbname":
            pass
        elif opcode in ["codecopy", "dloadbytes"]:
            assembly.append("CODECOPY")
        elif opcode == "jnz":
            # jump if not zero
            if_nonzero_label = inst.operands[1]
            if_zero_label = inst.operands[2]
            assembly.append(f"_sym_{if_nonzero_label.value}")
            assembly.append("JUMPI")

            # make sure the if_zero_label will be optimized out
            # assert if_zero_label == next(iter(inst.parent.cfg_out)).label

            assembly.append(f"_sym_{if_zero_label.value}")
            assembly.append("JUMP")

        elif opcode == "jmp":
            assert isinstance(inst.operands[0], IRLabel)
            assembly.append(f"_sym_{inst.operands[0].value}")
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
                    f"_sym_{target.value}",
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
        else:
            raise Exception(f"Unknown opcode: {opcode}")

        # Step 6: Emit instructions output operands (if any)
        if inst.output is not None:
            if "call" in inst.opcode and inst.output not in next_liveness:
                self.pop(assembly, stack)
            elif inst.output in next_liveness:
                # peek at next_liveness to find the next scheduled item,
                # and optimistically swap with it
                next_scheduled = list(next_liveness)[-1]
                self.swap_op(assembly, stack, next_scheduled)

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
        self.swap(assembly, stack, stack.get_depth(op))

    def dup_op(self, assembly, stack, op):
        self.dup(assembly, stack, stack.get_depth(op))


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
