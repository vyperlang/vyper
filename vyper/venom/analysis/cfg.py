from typing import Iterator, MutableMapping
from weakref import WeakKeyDictionary

from vyper.utils import OrderedSet
from vyper.venom.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock


class CFGAnalysis(IRAnalysis):
    """
    Compute control flow graph information for each basic block in the function.
    """

    _dfs: OrderedSet[IRBasicBlock]
    _cfg_in: MutableMapping[IRBasicBlock, OrderedSet[IRBasicBlock]]
    _cfg_out: MutableMapping[IRBasicBlock, OrderedSet[IRBasicBlock]]
    _reachable: MutableMapping[IRBasicBlock, bool]

    def analyze(self) -> None:
        fn = self.function

        self._dfs = OrderedSet()
        # use weak key dictionary since if a bb gets removed (for being
        # unreachable), it should fall out of the cfg analysis.
        self._cfg_in = WeakKeyDictionary()
        self._cfg_out = WeakKeyDictionary()
        self._reachable = WeakKeyDictionary()

        for bb in fn.get_basic_blocks():
            self._cfg_in[bb] = OrderedSet()
            self._cfg_out[bb] = OrderedSet()
            self._reachable[bb] = False

        for bb in fn.get_basic_blocks():
            # order of cfg_out matters to performance!
            for next_bb in reversed(bb.out_bbs):
                self._cfg_out[bb].add(next_bb)
                self._cfg_in[next_bb].add(bb)

        self._compute_dfs_post_r(self.function.entry)

    def add_cfg_in(self, bb: IRBasicBlock, pred: IRBasicBlock):
        self._cfg_in[bb].add(pred)

    def add_cfg_out(self, bb, succ):
        self._cfg_out[bb].add(succ)

    def remove_cfg_in(self, bb: IRBasicBlock, pred: IRBasicBlock):
        self._cfg_in[bb].remove(pred)

    def remove_cfg_out(self, bb: IRBasicBlock, succ: IRBasicBlock):
        self._cfg_out[bb].remove(succ)

    def cfg_in(self, bb: IRBasicBlock) -> OrderedSet[IRBasicBlock]:
        return self._cfg_in[bb]

    def cfg_out(self, bb: IRBasicBlock) -> OrderedSet[IRBasicBlock]:
        return self._cfg_out[bb]

    def is_reachable(self, bb: IRBasicBlock) -> bool:
        return self._reachable[bb]

    def is_normalized(self) -> bool:
        """
        Check if function is normalized. A function is normalized if in the
        CFG, no basic block simultaneously has multiple inputs and outputs.
        That is, a basic block can be jumped to *from* multiple blocks, or it
        can jump *to* multiple blocks, but it cannot simultaneously do both.
        Having a normalized CFG makes calculation of stack layout easier when
        emitting assembly.
        """
        for bb in self.function.get_basic_blocks():
            # Ignore if there are no multiple predecessors
            if len(self._cfg_in[bb]) <= 1:
                continue

            # Check if there is a branching jump at the end
            # of one of the predecessors
            for in_bb in self._cfg_in[bb]:
                if len(self._cfg_out[in_bb]) > 1:
                    return False

        # The function is normalized
        return True

    def _compute_dfs_post_r(self, bb):
        if self._reachable[bb]:
            return
        self._reachable[bb] = True

        for out_bb in self._cfg_out[bb]:
            self._compute_dfs_post_r(out_bb)

        self._dfs.add(bb)

    @property
    def dfs_pre_walk(self) -> Iterator[IRBasicBlock]:
        visited: OrderedSet[IRBasicBlock] = OrderedSet()

        def _visit_dfs_pre_r(bb: IRBasicBlock):
            if bb in visited:
                return
            visited.add(bb)

            yield bb

            for out_bb in self._cfg_out[bb]:
                yield from _visit_dfs_pre_r(out_bb)

        yield from _visit_dfs_pre_r(self.function.entry)

    @property
    def dfs_post_walk(self) -> Iterator[IRBasicBlock]:
        return iter(self._dfs)

    def invalidate(self):
        from vyper.venom.analysis import (
            DFGAnalysis,
            DominatorTreeAnalysis,
            LivenessAnalysis,
            ReachableAnalysis,
        )

        # just in case somebody is holding onto a bad reference to this
        del self._cfg_in
        del self._cfg_out
        del self._reachable
        del self._dfs

        # just to be on the safe side, but this is probably not needed.
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

        self.analyses_cache.invalidate_analysis(DominatorTreeAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(ReachableAnalysis)
