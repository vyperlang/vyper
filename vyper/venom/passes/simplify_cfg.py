from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.passes.base_pass import IRPass


class SimplifyCFGPass(IRPass):
    visited: OrderedSet

    def _merge_blocks(self, a: IRBasicBlock, b: IRBasicBlock):
        a.instructions.pop()  # pop terminating instruction
        for inst in b.instructions:
            assert inst.opcode != "phi", f"Instruction should never be phi {b}"
            inst.parent = a
            a.instructions.append(inst)

        # Update CFG
        a.cfg_out = b.cfg_out

        for next_bb in a.cfg_out:
            next_bb.remove_cfg_in(b)
            next_bb.add_cfg_in(a)

            for inst in next_bb.instructions:
                # assume phi instructions are at beginning of bb
                if inst.opcode != "phi":
                    break
                inst.operands[inst.operands.index(b.label)] = a.label

        self.function.remove_basic_block(b)

    def _merge_jump(self, a: IRBasicBlock, b: IRBasicBlock):
        next_bb = b.cfg_out.first()
        jump_inst = a.instructions[-1]
        assert b.label in jump_inst.operands, f"{b.label} {jump_inst.operands}"
        jump_inst.operands[jump_inst.operands.index(b.label)] = next_bb.label

        self._replace_label(b.label, next_bb.label)

        # Update CFG
        a.remove_cfg_out(b)
        a.add_cfg_out(next_bb)
        next_bb.remove_cfg_in(b)
        next_bb.add_cfg_in(a)

        self.function.remove_basic_block(b)

    def _collapse_chained_blocks_r(self, bb: IRBasicBlock):
        """
        DFS into the cfg and collapse blocks with a single predecessor to the predecessor
        """
        if len(bb.cfg_out) == 1:
            next_bb = bb.cfg_out.first()
            if len(next_bb.cfg_in) == 1:
                self._merge_blocks(bb, next_bb)
                self._collapse_chained_blocks_r(bb)
                return
        elif len(bb.cfg_out) == 2:
            bb_out = bb.cfg_out.copy()
            for next_bb in bb_out:
                if (
                    len(next_bb.cfg_in) == 1
                    and len(next_bb.cfg_out) == 1
                    and len(next_bb.instructions) == 1
                ):
                    self._merge_jump(bb, next_bb)
                    self._collapse_chained_blocks_r(bb)
                    return

        if bb in self.visited:
            return
        self.visited.add(bb)

        for bb_out in bb.cfg_out:
            self._collapse_chained_blocks_r(bb_out)

    def _collapse_chained_blocks(self, entry: IRBasicBlock):
        """
        Collapse blocks with a single predecessor to their predecessor
        """
        self.visited = OrderedSet()
        self._collapse_chained_blocks_r(entry)

    def _replace_label(self, original_label: IRLabel, replacement_label: IRLabel):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                inst.replace_operands({original_label: replacement_label})

    def run_pass(self):
        fn = self.function
        entry = fn.entry

        self.analyses_cache.request_analysis(CFGAnalysis)
        changes = fn.remove_unreachable_blocks()
        if changes:
            self.analyses_cache.force_analysis(CFGAnalysis)

        for _ in range(fn.num_basic_blocks):  # essentially `while True`
            self._collapse_chained_blocks(entry)
            self.analyses_cache.force_analysis(CFGAnalysis)
            if fn.remove_unreachable_blocks() == 0:
                break
        else:
            raise CompilerPanic("Too many iterations collapsing chained blocks")

        self.analyses_cache.invalidate_analysis(CFGAnalysis)
