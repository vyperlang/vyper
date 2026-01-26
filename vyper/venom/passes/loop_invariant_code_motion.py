from __future__ import annotations

from dataclasses import dataclass

from vyper.utils import OrderedSet
from vyper.venom import effects
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.passes.base_pass import IRPass


@dataclass
class LoopInfo:
    header: IRBasicBlock
    blocks: OrderedSet[IRBasicBlock]
    latches: OrderedSet[IRBasicBlock]
    preheader: IRBasicBlock | None = None


class LoopInvariantCodeMotionPass(IRPass):
    """
    Move computations whose operands do not change inside a loop outside of the
    loop body so they execute only once.
    """

    cfg: CFGAnalysis
    dom: DominatorTreeAnalysis

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)

        changed = False
        loops = self._find_loops()
        loops = self._filter_nested_loops(loops)
        for loop in loops:
            if loop.preheader is None:
                continue
            if self._hoist_loop(loop):
                changed = True

        if changed:
            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _find_loops(self) -> list[LoopInfo]:
        loops: dict[IRBasicBlock, LoopInfo] = {}

        for bb in self.function.get_basic_blocks():
            for succ in self.cfg.cfg_out(bb):
                if not self.dom.dominates(succ, bb):
                    continue

                header = succ
                loop_nodes = self._compute_loop_nodes(header, bb)
                info = loops.get(header)
                if info is None:
                    info = LoopInfo(header, loop_nodes, OrderedSet([bb]))
                    loops[header] = info
                else:
                    info.blocks.update(loop_nodes)
                    info.latches.add(bb)

        for info in loops.values():
            info.preheader = self._find_preheader(info)

        # process inner loops first to allow hoisting to cascade outward
        return sorted(loops.values(), key=lambda loop: len(loop.blocks))

    def _filter_nested_loops(self, loops: list[LoopInfo]) -> list[LoopInfo]:
        if len(loops) < 2:
            return loops

        nested_headers: set[IRBasicBlock] = set()
        for loop in loops:
            for other in loops:
                if loop is other:
                    continue
                if loop.header in other.blocks or other.header in loop.blocks:
                    nested_headers.add(loop.header)
                    break

        if not nested_headers:
            return loops
        return [loop for loop in loops if loop.header not in nested_headers]

    def _compute_loop_nodes(
        self, header: IRBasicBlock, latch: IRBasicBlock
    ) -> OrderedSet[IRBasicBlock]:
        nodes = OrderedSet([header, latch])
        stack = [latch]

        while stack:
            bb = stack.pop()
            for pred in self.cfg.cfg_in(bb):
                if pred in nodes:
                    continue
                nodes.add(pred)
                stack.append(pred)

        return nodes

    def _find_preheader(self, loop: LoopInfo) -> IRBasicBlock | None:
        predecessors = [pred for pred in self.cfg.cfg_in(loop.header) if pred not in loop.blocks]
        if len(predecessors) != 1:
            return None

        return predecessors[0]

    def _hoist_loop(self, loop: LoopInfo) -> bool:
        invariants = self._collect_loop_invariants(loop)
        if not invariants:
            return False

        assert loop.preheader is not None
        for inst in invariants:
            self._move_to_preheader(inst, loop.preheader)
        return True

    def _collect_loop_defs(self, loop_blocks: OrderedSet[IRBasicBlock]) -> dict:
        defs: dict = {}
        for bb in loop_blocks:
            # include phi/param defs so loop-variant values aren't treated as invariant
            for inst in bb.instructions:
                for out in inst.get_outputs():
                    defs.setdefault(out, []).append(inst)
        return defs

    def _collect_loop_invariants(self, loop: LoopInfo) -> list[IRInstruction]:
        loop_defs = self._collect_loop_defs(loop.blocks)
        invariants: OrderedSet[IRInstruction] = OrderedSet()

        progress = True
        while progress:
            progress = False
            for bb in loop.blocks:
                for inst in bb.body_instructions:
                    if inst in invariants:
                        continue
                    if not self._is_candidate(inst):
                        continue
                    if not self._dominates_all_latches(inst.parent, loop.latches):
                        continue
                    if self._uses_loop_variant(inst, loop_defs, invariants):
                        continue

                    invariants.add(inst)
                    progress = True

        return list(invariants)

    def _is_candidate(self, inst: IRInstruction) -> bool:
        if inst.opcode == "nop":
            return False
        if inst.is_volatile or inst.is_bb_terminator:
            return False
        if not inst.has_outputs:
            return False
        if inst.get_read_effects() != effects.EMPTY:
            return False
        if inst.get_write_effects() != effects.EMPTY:
            return False
        return True

    def _dominates_all_latches(self, bb: IRBasicBlock, latches: OrderedSet[IRBasicBlock]) -> bool:
        for latch in latches:
            if not self.dom.dominates(bb, latch):
                return False
        return True

    def _uses_loop_variant(
        self, inst: IRInstruction, loop_defs: dict, invariants: OrderedSet[IRInstruction]
    ) -> bool:
        for operand in inst.get_input_variables():
            defs = loop_defs.get(operand)
            if not defs:
                continue
            if len(defs) == 1 and defs[0] in invariants:
                continue
            return True

        return False

    def _move_to_preheader(self, inst: IRInstruction, preheader: IRBasicBlock):
        parent = inst.parent
        parent.remove_instruction(inst)

        insert_idx = len(preheader.instructions)
        if preheader.is_terminated:
            insert_idx -= 1

        preheader.insert_instruction(inst, index=insert_idx)
