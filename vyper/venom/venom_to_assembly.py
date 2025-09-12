from __future__ import annotations

from typing import Any, Iterable

from vyper.evm.assembler.instructions import DATA_ITEM, PUSH, DataHeader
from vyper.exceptions import CompilerPanic, StackTooDeep
from vyper.ir.compile_ir import (
    PUSH_OFST,
    PUSHLABEL,
    AssemblyInstruction,
    Label,
    TaggedInstruction,
    optimize_assembly,
)
from vyper.utils import MemoryPositions, OrderedSet, wrap256
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysesCache, LivenessAnalysis
from vyper.venom.basicblock import (
    PSEUDO_INSTRUCTION,
    TEST_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRContext, IRFunction
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
        "codecopy",
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

_REVERT_POSTAMBLE = [Label("revert"), *PUSH(0), "DUP1", "REVERT"]


def apply_line_numbers(inst: IRInstruction, asm) -> list[str]:
    ret = []
    for op in asm:
        if isinstance(op, str) and not isinstance(op, TaggedInstruction):
            ret.append(TaggedInstruction(op, inst.ast_source, inst.error_msg))
        else:
            ret.append(op)
    return ret  # type: ignore


def _as_asm_symbol(label: IRLabel) -> Label:
    # Lower an IRLabel to an assembly symbol
    return Label(label.value)


def _ofst(label: Label, value: int) -> list[Any]:
    # resolve at compile time using magic PUSH_OFST op
    return [PUSH_OFST(label, value)]


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
    visited_basicblocks: OrderedSet  # {IRBasicBlock}
    liveness: LivenessAnalysis
    dfg: DFGAnalysis
    cfg: CFGAnalysis

    def __init__(self, ctx: IRContext):
        # TODO: maybe just accept a single IRContext
        self.ctx = ctx
        self.label_counter = 0
        self.visited_basicblocks = OrderedSet()

    def mklabel(self, name: str) -> Label:
        self.label_counter += 1
        return Label(f"{name}_{self.label_counter}")

    def generate_evm_assembly(self, no_optimize: bool = False) -> list[AssemblyInstruction]:
        self.visited_basicblocks = OrderedSet()
        self.label_counter = 0

        asm: list[AssemblyInstruction] = []

        for fn in self.ctx.functions.values():
            ac = IRAnalysesCache(fn)

            self.liveness = ac.request_analysis(LivenessAnalysis)
            self.dfg = ac.request_analysis(DFGAnalysis)
            self.cfg = ac.request_analysis(CFGAnalysis)

            assert self.cfg.is_normalized(), "Non-normalized CFG!"

            self._generate_evm_for_basicblock_r(asm, fn.entry, StackModel())

        asm.extend(_REVERT_POSTAMBLE)
        # Append data segment
        for data_section in self.ctx.data_segment:
            label = data_section.label
            asm_data_section: list[AssemblyInstruction] = []
            asm_data_section.append(DataHeader(_as_asm_symbol(label)))
            for item in data_section.data_items:
                data = item.data
                if isinstance(data, IRLabel):
                    asm_data_section.append(DATA_ITEM(_as_asm_symbol(data)))
                else:
                    assert isinstance(data, bytes)
                    asm_data_section.append(DATA_ITEM(data))

            asm.extend(asm_data_section)

        if no_optimize is False:
            optimize_assembly(asm)

        return asm

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
                    assembly.append(PUSHLABEL(_as_asm_symbol(op)))
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

    def _prepare_stack_for_function(self, asm, fn: IRFunction, stack: StackModel):
        last_param = None
        for inst in fn.entry.instructions:
            if inst.opcode != "param":
                # note: always well defined if the bb is terminated
                next_liveness = self.liveness.live_vars_at(inst)
                break

            last_param = inst

            assert inst.output is not None  # help mypy
            stack.push(inst.output)

        # no params (only applies for global entry function)
        if last_param is None:
            return

        to_pop: list[IRVariable] = []
        for var in stack._stack:
            if var not in next_liveness:
                assert isinstance(var, IRVariable)  # help mypy
                to_pop.append(var)

        self.popmany(asm, to_pop, stack)

        self._optimistic_swap(asm, last_param, next_liveness, stack)

    def popmany(self, asm, to_pop: Iterable[IRVariable], stack):
        to_pop = list(to_pop)
        # small heuristic: pop from shallowest first.
        to_pop.sort(key=lambda var: -stack.get_depth(var))

        # NOTE: we could get more fancy and try to optimize the swap
        # operations here, there is probably some more room for optimization.
        for var in to_pop:
            depth = stack.get_depth(var)

            if depth != 0:
                self.swap(asm, stack, depth)
            self.pop(asm, stack)

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

        fn = basicblock.parent
        if basicblock == fn.entry:
            self._prepare_stack_for_function(asm, fn, stack)

        if len(self.cfg.cfg_in(basicblock)) == 1:
            self.clean_stack_from_cfg_in(asm, basicblock, stack)

        all_insts = [inst for inst in basicblock.instructions if inst.opcode != "param"]

        for i, inst in enumerate(all_insts):
            if i + 1 < len(all_insts):
                next_liveness = self.liveness.live_vars_at(all_insts[i + 1])
            else:
                next_liveness = self.liveness.out_vars(basicblock)

            asm.extend(self._generate_evm_for_instruction(inst, stack, next_liveness))

        if DEBUG_SHOW_COST:
            print(" ".join(map(str, asm)), file=sys.stderr)
            print("\n", file=sys.stderr)

        ref.extend(asm)

        for bb in self.cfg.cfg_out(basicblock):
            self._generate_evm_for_basicblock_r(ref, bb, stack.copy())

    # pop values from stack at entry to bb
    # note this produces the same result(!) no matter which basic block
    # we enter from in the CFG.
    def clean_stack_from_cfg_in(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        # the input block is a splitter block, like jnz or djmp
        assert len(in_bbs := self.cfg.cfg_in(basicblock)) == 1
        in_bb = in_bbs.first()
        assert len(self.cfg.cfg_out(in_bb)) > 1

        # inputs is the input variables we need from in_bb
        inputs = self.liveness.input_vars_from(in_bb, basicblock)

        # layout is the output stack layout for in_bb (which works
        # for all possible cfg_outs from the in_bb, in_bb is responsible
        # for making sure its output stack layout works no matter which
        # bb it jumps into).
        layout = self.liveness.out_vars(in_bb)
        to_pop = list(layout.difference(inputs))
        self.popmany(asm, to_pop, stack)

    def _generate_evm_for_instruction(
        self, inst: IRInstruction, stack: StackModel, next_liveness: OrderedSet
    ) -> list[str]:
        assembly: list[AssemblyInstruction] = []
        opcode = inst.opcode

        #
        # generate EVM for op
        #

        # Step 1: Apply instruction special stack manipulations

        if opcode in ["jmp", "djmp", "jnz", "invoke"]:
            operands = list(inst.get_non_label_operands())

        elif opcode in ("alloca", "palloca", "calloca"):
            assert len(inst.operands) == 3, inst
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
            assembly.extend(_ofst(_as_asm_symbol(label), ofst.value))
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
            assert len(self.cfg.cfg_out(inst.parent)) == 1
            next_bb = self.cfg.cfg_out(inst.parent).first()

            # guaranteed by cfg normalization+simplification
            assert len(self.cfg.cfg_in(next_bb)) > 1

            target_stack = self.liveness.input_vars_from(inst.parent, next_bb)
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
        elif opcode in ("alloca", "palloca", "calloca"):
            pass
        elif opcode == "param":
            pass
        elif opcode == "assign":
            pass
        elif opcode == "dbname":
            pass
        elif opcode == "jnz":
            # jump if not zero
            if_nonzero_label, if_zero_label = inst.get_label_operands()
            assembly.append(PUSHLABEL(_as_asm_symbol(if_nonzero_label)))
            assembly.append("JUMPI")

            # make sure the if_zero_label will be optimized out
            # assert if_zero_label == next(iter(inst.parent.cfg_out)).label

            assembly.append(PUSHLABEL(_as_asm_symbol(if_zero_label)))
            assembly.append("JUMP")

        elif opcode == "jmp":
            (target,) = inst.operands
            assert isinstance(target, IRLabel)
            assembly.append(PUSHLABEL(_as_asm_symbol(target)))
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
            return_label = self.mklabel("return_label")
            assembly.extend(
                [PUSHLABEL(return_label), PUSHLABEL(_as_asm_symbol(target)), "JUMP", return_label]
            )
        elif opcode == "ret":
            assembly.append("JUMP")
        elif opcode == "return":
            assembly.append("RETURN")
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
            assembly.extend(["ISZERO", PUSHLABEL(Label("revert")), "JUMPI"])
        elif opcode == "assert_unreachable":
            end_symbol = self.mklabel("reachable")
            assembly.extend([PUSHLABEL(end_symbol), "JUMPI", "INVALID", end_symbol])
        elif opcode == "iload":
            addr = inst.operands[0]
            mem_deploy_end = self.ctx.constants["mem_deploy_end"]
            if isinstance(addr, IRLiteral):
                ptr = mem_deploy_end + addr.value
                assembly.extend(PUSH(ptr))
            else:
                assembly.extend([*PUSH(mem_deploy_end), "ADD"])
            assembly.append("MLOAD")
        elif opcode == "istore":
            addr = inst.operands[1]
            mem_deploy_end = self.ctx.constants["mem_deploy_end"]
            if isinstance(addr, IRLiteral):
                ptr = mem_deploy_end + addr.value
                assembly.extend(PUSH(ptr))
            else:
                assembly.extend([*PUSH(mem_deploy_end), "ADD"])
            assembly.append("MSTORE")
        elif opcode == "log":
            assembly.extend([f"LOG{log_topic_count}"])
        elif opcode == "nop":
            pass
        elif opcode in PSEUDO_INSTRUCTION:  # pragma: nocover
            raise CompilerPanic(f"Bad instruction: {opcode}")
        elif opcode in TEST_INSTRUCTIONS:  # pragma: nocover
            raise CompilerPanic(f"Bad instruction: {opcode}")
        else:
            raise Exception(f"Unknown opcode: {opcode}")

        # Step 6: Emit instructions output operands (if any)
        if inst.output is not None:
            if inst.output not in next_liveness:
                self.pop(assembly, stack)
            else:
                self._optimistic_swap(assembly, inst, next_liveness, stack)

        return apply_line_numbers(inst, assembly)

    def _optimistic_swap(self, assembly, inst, next_liveness, stack):
        # heuristic: peek at next_liveness to find the next scheduled
        # item, and optimistically swap with it
        if DEBUG_SHOW_COST:
            stack0 = stack.copy()

        # if there are no live vars at the next point, nothing to schedule
        if len(next_liveness) == 0:
            return

        next_scheduled = next_liveness.last()
        cost = 0
        if not self.dfg.are_equivalent(inst.output, next_scheduled):
            cost = self.swap_op(assembly, stack, next_scheduled)

        if DEBUG_SHOW_COST and cost != 0:
            print("ENTER", inst, file=sys.stderr)
            print("  HAVE", stack0, file=sys.stderr)
            print("  NEXT LIVENESS", next_liveness, file=sys.stderr)
            print("  NEW_STACK", stack, file=sys.stderr)

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
