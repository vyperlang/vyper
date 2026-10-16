from dataclasses import dataclass

from vyper.evm.address_space import MEMORY
from vyper.utils import OrderedSet
from vyper.venom.analysis.base_ptr_analysis import BasePtrAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.analysis.loop_detection import NaturalLoopDetectionAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRVariable
from vyper.venom.effects import EMPTY, Effects
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import Allocation
from vyper.venom.passes.base_pass import IRPass

UNINTERESTING_OPCODES = frozenset(
    [
        "calldatasize",
        "gaslimit",
        "address",
        "codesize",
        "assign",
        "phi",
        "source",
        "nop",
        "returndatasize",
        "gasprice",
        "gas",
        "origin",
        "coinbase",
        "timestamp",
        "number",
        "prevrandao",
        "chainid",
        "basefee",
        "blobbasefee",
        "pc",
    ]
)


def cannot_hoist(inst: IRInstruction) -> bool:
    return inst.is_param or inst.is_phi or inst.is_volatile


def _ignore_instruction(inst: IRInstruction) -> bool:
    if inst.is_param:
        return True
    if inst.opcode in UNINTERESTING_OPCODES:
        return True
    else:
        return inst.opcode == "add" and isinstance(inst.operands[1], IRLabel)


@dataclass
class _LoopEffects:
    writes: Effects
    # None represents a write not confined to a known allocation.
    memory_writes: set[Allocation | None]


class LoopInvariantHoisting(IRPass):
    """
    This pass detects invariants in loops and hoists them above the loop body.
    Any VOLATILE_INSTRUCTIONS, BB_TERMINATORS CFG_ALTERING_INSTRUCTIONS are ignored
    """

    function: IRFunction
    loops: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    dfg: DFGAnalysis
    gas_heuristic: int

    def run_pass(self, /, gas_heuristic: int = 2):
        self.gas_heuristic = gas_heuristic
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.loop_analysis = self.analyses_cache.request_analysis(NaturalLoopDetectionAnalysis)
        self.loops = self.loop_analysis.loops
        invalidate = False
        while True:
            change = False
            for header, loop in self.loops.items():
                hoistable: list[IRInstruction] = self._get_hoistable_loop(loop)
                if len(hoistable) == 0:
                    continue
                change |= True
                self._hoist(header, hoistable)
            if not change:
                break
            invalidate = True

        # only need to invalidate if you did some hoisting
        if invalidate:
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _hoist(self, header: IRBasicBlock, hoistable: list[IRInstruction]):
        target_bb = self.loop_analysis.get_pre_header(header)
        assert target_bb is not None
        for inst in hoistable:
            bb = inst.parent
            bb.remove_instruction(inst)
            target_bb.insert_instruction(inst, index=len(target_bb.instructions) - 1)

    def _get_loop_effects_write(self, loop: OrderedSet[IRBasicBlock]) -> _LoopEffects:
        res = _LoopEffects(EMPTY, set())
        for bb in loop:
            assert isinstance(bb, IRBasicBlock)  # help mypy
            for inst in bb.instructions:
                writes = inst.get_write_effects()
                res.writes |= writes
                if writes & Effects.MEMORY != EMPTY:
                    loc = self.base_ptr.get_write_location(inst, MEMORY)
                    res.memory_writes.add(loc.alloca)
        return res

    def _get_hoistable_loop(self, loop: OrderedSet[IRBasicBlock]) -> list[IRInstruction]:
        cannot_hoist_insts: set[IRInstruction] = set()
        loop_effects = self._get_loop_effects_write(loop)
        while True:
            orig = cannot_hoist_insts.copy()
            for bb in loop:
                self._handle_bb(bb, loop_effects, cannot_hoist_insts)

            if orig == cannot_hoist_insts:
                break

        result = list()
        for bb in loop:
            for inst in bb.instructions:
                if _ignore_instruction(inst):
                    continue
                if inst not in cannot_hoist_insts:
                    tmp = []
                    cost: int = inst.gas_cost
                    dependecies = self._get_dependencies(inst, cannot_hoist_insts, loop)
                    for dep in dependecies:
                        cost += dep.gas_cost
                        if dep in result or dep in tmp:
                            continue
                        tmp.append(dep)
                    if cost >= self.gas_heuristic:
                        result.extend(tmp)
                        result.append(inst)
        return result

    def _get_dependencies(
        self,
        inst: IRInstruction,
        cannot_hoists_insts: set[IRInstruction],
        loop: OrderedSet[IRBasicBlock],
    ) -> OrderedSet[IRInstruction]:
        res: OrderedSet[IRInstruction] = OrderedSet()
        for op in inst.operands:
            if not isinstance(op, IRVariable):
                continue
            source = self.dfg.get_producing_instruction(op)
            assert source is not None
            if source.parent not in loop:
                continue
            # should not create any trees since we can hoist it
            source_deps = self._get_dependencies(source, cannot_hoists_insts, loop)
            res.addmany(source_deps)
            assert source not in cannot_hoists_insts
            res.add(source)
        return res

    def _handle_bb(
        self, bb: IRBasicBlock, loop_effects: _LoopEffects, cannot_hoist_insts: set[IRInstruction]
    ):
        for inst in bb.instructions:
            if not self._can_hoist_instruction_ignore_assign(
                inst, loop_effects, cannot_hoist_insts
            ):
                cannot_hoist_insts.add(inst)

    def _can_hoist_instruction_ignore_assign(
        self,
        inst: IRInstruction,
        loop_effects: _LoopEffects,
        cannot_hoist_insts: set[IRInstruction],
    ) -> bool:
        if cannot_hoist(inst):
            return False
        conflicts = inst.get_read_effects() & loop_effects.writes
        if conflicts & ~Effects.MEMORY != EMPTY:
            return False
        if conflicts & Effects.MEMORY != EMPTY:
            alloca = self.base_ptr.get_read_location(inst, MEMORY).alloca
            # Distinct abstract allocations cannot alias. Unknown reads or
            # writes still conflict with every allocation.
            if alloca is None or None in loop_effects.memory_writes:
                return False
            if alloca in loop_effects.memory_writes:
                return False
        for op in inst.operands:
            if not isinstance(op, IRVariable):
                continue
            source = self.dfg.get_producing_instruction(op)
            if source in cannot_hoist_insts:
                return False
        return True
