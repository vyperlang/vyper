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
        self._spill_free_slots: list[int] = []
        self._spill_slot_offsets: dict[IRFunction, list[int]] = {}
        self._spill_insert_index: dict[IRFunction, int] = {}
        self._next_spill_offset = MemoryPositions.STACK_SPILL_BASE
        self._next_spill_alloca_id = 0
        self._current_function: IRFunction | None = None

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

            self._current_function = fn
            self._prepare_spill_state(fn)
            self._spill_free_slots = []

            self._generate_evm_for_basicblock_r(asm, fn.entry, StackModel(), {})
            self._current_function = None

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
        self,
        assembly: list,
        stack: StackModel,
        stack_ops: list[IROperand],
        spilled: dict[IROperand, int],
        dry_run: bool = False,
    ) -> int:
        if dry_run:
            assert len(assembly) == 0, "Dry run should not work on assembly"
            stack = stack.copy()
            spilled = spilled.copy()
            spill_free_snapshot = self._spill_free_slots.copy()
        else:
            spill_free_snapshot = []

        if len(stack_ops) == 0:
            return 0

        assert len(stack_ops) == len(
            set(stack_ops)
        ), f"duplicated stack {stack_ops}"  # precondition

        cost = 0
        for i, op in enumerate(stack_ops):
            final_stack_depth = -(len(stack_ops) - i - 1)

            depth = stack.get_depth(op)

            if depth == StackModel.NOT_IN_STACK:
                if isinstance(op, IRVariable) and op in spilled:
                    self._restore_spilled_operand(assembly, stack, spilled, op, dry_run=dry_run)
                    depth = stack.get_depth(op)
                else:
                    raise CompilerPanic(f"Variable {op} not in stack")

            if depth < -16:
                if not self._reduce_depth_via_spill(
                    assembly, stack, spilled, stack_ops, op, depth, dry_run
                ):
                    depth = stack.get_depth(op)
                else:
                    depth = stack.get_depth(op)

            if depth == final_stack_depth:
                continue

            to_swap = stack.peek(final_stack_depth)
            if self.dfg.are_equivalent(op, to_swap):
                # perform a "virtual" swap
                stack.poke(final_stack_depth, op)
                stack.poke(depth, to_swap)
                continue

            cost += self.swap(assembly, stack, depth, dry_run)
            cost += self.swap(assembly, stack, final_stack_depth, dry_run)

        assert stack._stack[-len(stack_ops) :] == stack_ops, (stack, stack_ops)

        if dry_run:
            self._spill_free_slots = spill_free_snapshot

        return cost

    def _reduce_depth_via_spill(
        self,
        assembly: list,
        stack: StackModel,
        spilled: dict[IROperand, int],
        stack_ops: list[IROperand],
        target_op: IROperand,
        depth: int,
        dry_run: bool,
    ) -> bool:
        while depth < -16:
            candidate_depth = self._select_spill_candidate(stack, stack_ops, depth)
            if candidate_depth is None:
                return False
            self._spill_operand(assembly, stack, spilled, candidate_depth, dry_run)
            depth = stack.get_depth(target_op)
            if depth == StackModel.NOT_IN_STACK:
                if isinstance(target_op, IRVariable) and target_op in spilled:
                    self._restore_spilled_operand(assembly, stack, spilled, target_op, dry_run)
                    depth = stack.get_depth(target_op)
                else:
                    return False
        return True

    def _select_spill_candidate(
        self, stack: StackModel, stack_ops: list[IROperand], target_depth: int
    ) -> int | None:
        forbidden = set(stack_ops)
        max_offset = min(16, -target_depth - 1, stack.height - 1)
        if max_offset < 0:
            return None
        for offset in range(0, max_offset + 1):
            depth = -offset
            candidate = stack.peek(depth)
            if candidate in forbidden:
                continue
            if not isinstance(candidate, IRVariable):
                continue
            return depth
        return None

    def _spill_operand(
        self,
        assembly: list,
        stack: StackModel,
        spilled: dict[IROperand, int],
        depth: int,
        dry_run: bool,
    ) -> None:
        operand = stack.peek(depth)
        assert isinstance(operand, IRVariable), operand

        if depth != 0:
            self.swap(assembly, stack, depth, dry_run)

        offset = self._get_spill_slot(operand, spilled, dry_run)
        assembly.extend(PUSH(offset))
        assembly.append("MSTORE")
        stack.pop()
        spilled[operand] = offset

    def _restore_spilled_operand(
        self,
        assembly: list,
        stack: StackModel,
        spilled: dict[IROperand, int],
        op: IRVariable,
        dry_run: bool = False,
    ) -> None:
        offset = spilled.pop(op)
        if not dry_run:
            self._spill_free_slots.append(offset)
        assembly.extend(PUSH(offset))
        assembly.append("MLOAD")
        stack.push(op)

    def _get_spill_slot(
        self, operand: IRVariable, spilled: dict[IROperand, int], dry_run: bool
    ) -> int:
        if operand in spilled:
            return spilled[operand]
        offset = self._acquire_spill_offset(dry_run)
        return offset

    def _release_dead_spills(
        self, spilled: dict[IROperand, int], live_set: OrderedSet[IRVariable]
    ) -> None:
        for op in list(spilled.keys()):
            if isinstance(op, IRVariable) and op in live_set:
                continue
            offset = spilled.pop(op)
            self._spill_free_slots.append(offset)

    def _emit_input_operands(
        self,
        assembly: list,
        inst: IRInstruction,
        ops: list[IROperand],
        stack: StackModel,
        next_liveness: OrderedSet[IRVariable],
        spilled: dict[IROperand, int],
    ) -> None:
        # PRE: we already have all the items on the stack that have
        # been scheduled to be killed. now it's just a matter of emitting
        # SWAPs, DUPs and PUSHes until we match the `ops` argument

        # to validate store expansion invariant -
        # each op is emitted at most once.
        seen: set[IROperand] = set()

        for op in ops:
            if isinstance(op, IRVariable) and op in spilled:
                self._restore_spilled_operand(assembly, stack, spilled, op)

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
            assert op not in seen, (inst, op, seen)
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

    def _prepare_spill_state(self, fn: IRFunction) -> None:
        if fn in self._spill_slot_offsets:
            return

        entry = fn.entry
        insert_idx = 0
        for inst in entry.instructions:
            if inst.opcode == "param":
                insert_idx += 1
            else:
                break

        self._spill_slot_offsets[fn] = []
        self._spill_insert_index[fn] = insert_idx

    def _allocate_spill_slot(self, fn: IRFunction) -> int:
        entry = fn.entry
        insert_idx = self._spill_insert_index[fn]

        offset = self._next_spill_offset
        self._next_spill_offset += 32

        offset_lit = IRLiteral(offset)
        size_lit = IRLiteral(32)
        id_lit = IRLiteral(self._next_spill_alloca_id)
        self._next_spill_alloca_id += 1

        output_var = fn.get_next_variable()
        inst = IRInstruction("alloca", [offset_lit, size_lit, id_lit], output_var)
        entry.insert_instruction(inst, insert_idx)
        self._spill_insert_index[fn] += 1
        self._spill_slot_offsets[fn].append(offset)
        return offset

    def _acquire_spill_offset(self, dry_run: bool) -> int:
        if self._spill_free_slots:
            return self._spill_free_slots.pop()
        if dry_run:
            return 0
        if self._current_function is None:
            offset = self._next_spill_offset
            self._next_spill_offset += 32
            return offset
        return self._allocate_spill_slot(self._current_function)

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
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel, spilled: dict[IROperand, int]
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

            asm.extend(self._generate_evm_for_instruction(inst, stack, next_liveness, spilled))

        if DEBUG_SHOW_COST:
            print(" ".join(map(str, asm)), file=sys.stderr)
            print("\n", file=sys.stderr)

        ref.extend(asm)

        for bb in self.cfg.cfg_out(basicblock):
            self._generate_evm_for_basicblock_r(ref, bb, stack.copy(), spilled.copy())

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
        self,
        inst: IRInstruction,
        stack: StackModel,
        next_liveness: OrderedSet,
        spilled: dict[IROperand, int],
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
        self._emit_input_operands(assembly, inst, operands, stack, next_liveness, spilled)

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
            self._stack_reorder(assembly, stack, list(target_stack), spilled)

        if inst.is_commutative:
            cost_no_swap = self._stack_reorder([], stack, operands, spilled, dry_run=True)
            operands[-1], operands[-2] = operands[-2], operands[-1]
            cost_with_swap = self._stack_reorder([], stack, operands, spilled, dry_run=True)
            if cost_with_swap > cost_no_swap:
                operands[-1], operands[-2] = operands[-2], operands[-1]

        cost = self._stack_reorder([], stack, operands, spilled, dry_run=True)
        if DEBUG_SHOW_COST and cost:
            print("ENTER", inst, file=sys.stderr)
            print("  HAVE", stack, file=sys.stderr)
            print("  WANT", operands, file=sys.stderr)
            print("  COST", cost, file=sys.stderr)

        # final step to get the inputs to this instruction ordered
        # correctly on the stack
        self._stack_reorder(assembly, stack, operands, spilled)

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

        self._release_dead_spills(spilled, next_liveness)

        return apply_line_numbers(inst, assembly)

    def _optimistic_swap(self, assembly, inst, next_liveness, stack):
        # heuristic: peek at next_liveness to find the next scheduled
        # item, and optimistically swap with it
        if DEBUG_SHOW_COST:
            stack0 = stack.copy()

        next_index = inst.parent.instructions.index(inst)
        next_inst = inst.parent.instructions[next_index + 1]

        if next_inst.is_bb_terminator:
            return
        # if there are no live vars at the next point, nothing to schedule
        if len(next_liveness) == 0:
            return

        next_scheduled = next_liveness.last()
        cost = 0
        if not self.dfg.are_equivalent(inst.output, next_scheduled):
            depth = stack.get_depth(next_scheduled)
            if depth is not StackModel.NOT_IN_STACK:
                cost = self.swap(assembly, stack, depth)

        if DEBUG_SHOW_COST and cost != 0:
            print("ENTER", inst, file=sys.stderr)
            print("  HAVE", stack0, file=sys.stderr)
            print("  NEXT LIVENESS", next_liveness, file=sys.stderr)
            print("  NEW_STACK", stack, file=sys.stderr)

    def pop(self, assembly, stack, num=1):
        stack.pop(num)
        assembly.extend(["POP"] * num)

    def _spill_stack_segment(
        self, assembly, stack, count: int, dry_run: bool
    ) -> tuple[list[IROperand], list[int], int]:
        spill_ops: list[IROperand] = []
        offsets: list[int] = []
        cost = 0

        for _ in range(count):
            op = stack.peek(0)
            spill_ops.append(op)

            offset = self._acquire_spill_offset(dry_run)
            offsets.append(offset)

            assembly.extend(PUSH(offset))
            assembly.append("MSTORE")
            stack.pop()
            cost += 2

        return spill_ops, offsets, cost

    def _restore_spilled_segment(
        self,
        assembly,
        stack,
        spill_ops: list[IROperand],
        offsets: list[int],
        desired_indices: list[int],
        dry_run: bool,
    ) -> int:
        cost = 0

        for idx in reversed(desired_indices):
            assembly.extend(PUSH(offsets[idx]))
            assembly.append("MLOAD")
            stack.push(spill_ops[idx])
            cost += 2

        if not dry_run:
            for offset in offsets:
                self._spill_free_slots.append(offset)

        return cost

    def swap(self, assembly, stack, depth, dry_run: bool = False) -> int:
        # Swaps of the top is no op
        if depth == 0:
            return 0

        swap_idx = -depth
        if swap_idx < 1:
            raise StackTooDeep(f"Unsupported swap depth {swap_idx}")
        if swap_idx <= 16:
            stack.swap(depth)
            assembly.append(_evm_swap_for(depth))
            return 1

        chunk_size = swap_idx + 1
        spill_ops, offsets, cost = self._spill_stack_segment(assembly, stack, chunk_size, dry_run)

        indices = list(range(chunk_size))
        if chunk_size == 1:
            desired_indices = indices
        else:
            desired_indices = [indices[-1]] + indices[1:-1] + [indices[0]]

        cost += self._restore_spilled_segment(
            assembly, stack, spill_ops, offsets, desired_indices, dry_run
        )
        return cost

    def dup(self, assembly, stack, depth, dry_run: bool = False):
        dup_idx = 1 - depth
        if dup_idx < 1:
            raise StackTooDeep(f"Unsupported dup depth {dup_idx}")
        if dup_idx <= 16:
            stack.dup(depth)
            assembly.append(_evm_dup_for(depth))
            return

        chunk_size = dup_idx
        spill_ops, offsets, _ = self._spill_stack_segment(assembly, stack, chunk_size, dry_run)

        indices = list(range(chunk_size))
        desired_indices = [indices[-1]] + indices

        self._restore_spilled_segment(assembly, stack, spill_ops, offsets, desired_indices, dry_run)

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
