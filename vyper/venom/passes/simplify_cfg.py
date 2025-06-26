from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.passes.base_pass import IRPass


class SimplifyCFGPass(IRPass):
    visited: OrderedSet
    cfg: CFGAnalysis

    def _merge_blocks(self, a: IRBasicBlock, b: IRBasicBlock):
        a.instructions.pop()  # pop terminating instruction
        for inst in b.instructions:
            assert inst.opcode != "phi", f"Instruction should never be phi {b}"
            inst.parent = a
            a.instructions.append(inst)

        # Update CFG
        self.cfg._cfg_out[a] = self.cfg._cfg_out[b]

        for next_bb in self.cfg.cfg_out(a):
            self.cfg.remove_cfg_in(next_bb, b)
            self.cfg.add_cfg_in(next_bb, a)

            for inst in next_bb.instructions:
                # assume phi instructions are at beginning of bb
                if inst.opcode != "phi":
                    break
                inst.operands[inst.operands.index(b.label)] = a.label

        self.function.remove_basic_block(b)

    def _merge_jump(self, a: IRBasicBlock, b: IRBasicBlock):
        next_bb = self.cfg.cfg_out(b).first()
        jump_inst = a.instructions[-1]
        assert b.label in jump_inst.operands, f"{b.label} {jump_inst.operands}"
        jump_inst.operands[jump_inst.operands.index(b.label)] = next_bb.label

        self._schedule_label_replacement(b.label, next_bb.label)

        # Update CFG
        self.cfg.remove_cfg_out(a, b)
        self.cfg.add_cfg_out(a, next_bb)
        self.cfg.remove_cfg_in(next_bb, b)
        self.cfg.add_cfg_in(next_bb, a)

        self.function.remove_basic_block(b)

    def _collapse_chained_blocks_r(self, bb: IRBasicBlock):
        """
        DFS into the cfg and collapse blocks with a single predecessor to the predecessor
        """
        if len((out_bbs := self.cfg.cfg_out(bb))) == 1:
            next_bb = out_bbs.first()
            if len(self.cfg.cfg_in(next_bb)) == 1:
                self._merge_blocks(bb, next_bb)
                self._collapse_chained_blocks_r(bb)
                return
        elif len(out_bbs := self.cfg.cfg_out(bb)) == 2:
            for next_bb in list(out_bbs):
                if (
                    len(self.cfg.cfg_in(next_bb)) == 1
                    and len(self.cfg.cfg_out(next_bb)) == 1
                    and len(next_bb.instructions) == 1
                ):
                    self._merge_jump(bb, next_bb)
                    self._collapse_chained_blocks_r(bb)
                    return

        if bb in self.visited:
            return
        self.visited.add(bb)

        for bb_out in self.cfg.cfg_out(bb):
            self._collapse_chained_blocks_r(bb_out)

    def _collapse_chained_blocks(self, entry: IRBasicBlock):
        """
        Collapse blocks with a single predecessor to their predecessor
        """
        self.visited = OrderedSet()
        self._collapse_chained_blocks_r(entry)

    def _schedule_label_replacement(self, original_label: IRLabel, replacement_label: IRLabel):
        assert original_label not in self.label_map
        self.label_map[original_label] = replacement_label

    def _replace_all_labels(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                inst.replace_operands(self.label_map)

    def remove_unreachable_blocks(self) -> int:
        # Remove unreachable basic blocks
        removed = set()

        for bb in list(self.function.get_basic_blocks()):
            if not self.cfg.is_reachable(bb):
                self.function.remove_basic_block(bb)
                removed.add(bb)

        # Remove phi instructions that reference removed basic blocks
        for bb in self.function.get_basic_blocks():
            for in_bb in list(self.cfg.cfg_in(bb)):
                if in_bb not in removed:
                    continue

                self.cfg.remove_cfg_in(bb, in_bb)

            # TODO: only run this if cfg_in changed
            self.fix_phi_instructions(bb)

        return len(removed)

    def fix_phi_instructions(self, bb):
        cfg_in_labels = tuple(in_bb.label for in_bb in self.cfg.cfg_in(bb))

        needs_sort = False
        for inst in bb.instructions:
            if inst.opcode != "phi":
                # perf todo: break
                continue

            # note: make a copy of the iterator, since it can be
            # modified inside the loop
            labels = list(inst.get_label_operands())
            for label in labels:
                if label not in cfg_in_labels:
                    needs_sort = True
                    inst.remove_phi_operand(label)

            op_len = len(inst.operands)
            if op_len == 2:
                inst.opcode = "assign"
                inst.operands = [inst.operands[1]]
            elif op_len == 0:
                inst.make_nop()

        if needs_sort:
            bb.instructions.sort(key=lambda inst: inst.opcode != "phi")

    def run_pass(self):
        fn = self.function
        entry = fn.entry

        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        changes = self.remove_unreachable_blocks()
        if changes:
            self.cfg = self.analyses_cache.force_analysis(CFGAnalysis)

        for _ in range(fn.num_basic_blocks):  # essentially `while True`
            self.label_map = {}
            self._collapse_chained_blocks(entry)
            self._replace_all_labels()
            self.cfg = self.analyses_cache.force_analysis(CFGAnalysis)
            if self.remove_unreachable_blocks() == 0:
                break
        else:
            raise CompilerPanic("Too many iterations collapsing chained blocks")

        self.analyses_cache.invalidate_analysis(CFGAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
