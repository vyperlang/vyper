from dataclasses import dataclass
from typing import MutableMapping

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, DominatorTreeAnalysis, IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRVariable


@dataclass
class Loop:
    header: IRBasicBlock
    body: OrderedSet[IRBasicBlock]
    back_edge_sources: list[IRBasicBlock]

    @property
    def back_edges(self) -> list[tuple[IRBasicBlock, IRBasicBlock]]:
        """A back edge is defined as an edge (B, A) where A dominates B"""
        return [(src, self.header) for src in self.back_edge_sources]


class LoopAnalysis(IRAnalysis):
    """ """

    cfg: CFGAnalysis
    dom: DominatorTreeAnalysis
    dfg: DFGAnalysis

    back_edges: list[tuple[IRBasicBlock, IRBasicBlock]]
    loops: list[Loop]

    def analyze(self):
        """
        Compute Loop Information
        """
        self.fn = self.function
        self.entry_block = self.fn.entry
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self._find_back_edges()
        self._construct_natural_loops()

    def _find_back_edges(self):
        self.back_edges = []

        # Only check reachable blocks to avoid dominance lookup errors
        reachable = self.dom.cfg_post_order
        for bb in self.fn.get_basic_blocks():
            if bb not in reachable:
                continue
            for succ in self.cfg.cfg_out(bb):
                if succ not in reachable:
                    continue
                if self.dom.dominates(succ, bb):
                    self.back_edges.append((bb, succ))

    def _construct_natural_loops(self):
        header_to_sources: MutableMapping[IRBasicBlock, list[IRBasicBlock]] = {}
        for src, header in self.back_edges:
            header_to_sources.setdefault(header, []).append(src)

        self.loops = []
        for header, sources in header_to_sources.items():
            body = self._compute_loop_body(header, sources)
            self.loops.append(Loop(header=header, body=body, back_edge_sources=sources))

    def _compute_loop_body(self, header, sources):
        body = OrderedSet([header])
        worklist = list(sources)

        while worklist:
            n = worklist.pop()
            if n in body:
                continue
            body.add(n)
            for pred in self.cfg.cfg_in(n):
                worklist.append(pred)

        return body

    def get_exit_nodes(self, loop: Loop) -> list[IRBasicBlock]:
        """An exit node is any successor of a loop node, outside of the loop"""
        return [succ for bb in loop.body for succ in self.cfg.cfg_out(bb) - loop.body]

    def get_preheader(self, loop: Loop) -> IRBasicBlock | None:
        """
        Get the preheader of a loop if it exists.

        A valid preheader must:
        1. Be the single predecessor from outside the loop
        2. Have the loop header as its only successor

        Returns None if no valid preheader exists.
        """
        outside_preds = [p for p in self.cfg.cfg_in(loop.header) if p not in loop.body]
        if len(outside_preds) != 1:
            return None

        preheader = outside_preds[0]
        # Preheader must have loop header as only successor
        if self.cfg.cfg_out(preheader) != OrderedSet([loop.header]):
            return None

        return preheader

    def is_variable_defined_in_loop(self, var: IRVariable, loop: Loop) -> bool:
        inst = self.dfg.get_producing_instruction(var)
        return inst.parent in loop.body if inst is not None else False
