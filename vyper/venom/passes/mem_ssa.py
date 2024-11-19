from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass


class MemSSA(IRPass):
    """
    This pass converts memory operations into Static Single Assignment (SSA) form.
    Similar to variable SSA but specifically for memory operations (mload/mstore).
    """

    dom: DominatorTreeAnalysis
    mem_defs: dict[int, OrderedSet[IRBasicBlock]]  # memory offset -> defining blocks

    def run_pass(self):
        fn = self.function

        # Request required analyses
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.analyses_cache.request_analysis(LivenessAnalysis)

        # Add phi nodes for memory operations
        self._add_mem_phi_nodes()
        
        # Initialize version tracking
        self.mem_version_counters = {}  # offset -> counter
        self.mem_version_stacks = {}    # offset -> version stack
        
        # Rename memory operations starting from entry block
        self._rename_mem_ops(fn.entry)
        
        # Clean up unnecessary phi nodes
        self._remove_degenerate_phis(fn.entry)

        # Invalidate liveness analysis since we modified instructions
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _compute_mem_defs(self):
        """
        Compute memory definition points in the function.
        """
        self.mem_defs = {}
        for bb in self.dom.dfs_walk:
            for inst in bb.instructions:
                if inst.opcode == "mstore":
                    offset = inst.operands[1].value if isinstance(inst.operands[1], IRLiteral) else None
                    if offset is not None:
                        if offset not in self.mem_defs:
                            self.mem_defs[offset] = OrderedSet()
                        self.mem_defs[offset].add(bb)

    def _add_mem_phi_nodes(self):
        """
        Add phi nodes for memory operations where necessary.
        """
        self._compute_mem_defs()
        work = {var: 0 for var in self.dom.dfs_walk}
        has_already = {var: 0 for var in self.dom.dfs_walk}
        i = 0

        # Iterate over all memory locations that are written to
        for offset, d in self.mem_defs.items():
            i += 1
            defs = list(d)
            while len(defs) > 0:
                bb = defs.pop()
                for dom in self.dom.dominator_frontiers[bb]:
                    if has_already[dom] >= i:
                        continue

                    self._place_mem_phi(offset, dom)
                    has_already[dom] = i
                    if work[dom] < i:
                        work[dom] = i
                        defs.append(dom)

    def _place_mem_phi(self, offset: int, basic_block: IRBasicBlock):
        """
        Place a phi node for a memory location in a basic block.
        """
        args: list[IROperand] = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue
            
            args.append(bb.label)
            args.append(IRVariable(f"mem{offset}"))

        basic_block.insert_instruction(IRInstruction("mphi", args, IRVariable(f"mem{offset}")), 0)

    def _rename_mem_ops(self, basic_block: IRBasicBlock):
        """
        Rename memory operations to maintain SSA form.
        """
        outs = []

        # Pre-action
        for inst in basic_block.instructions:
            if inst.opcode == "mstore":
                offset = inst.operands[1].value if isinstance(inst.operands[1], IRLiteral) else None
                if offset is not None:
                    if offset not in self.mem_version_counters:
                        self.mem_version_counters[offset] = 0
                        self.mem_version_stacks[offset] = [0]
                    
                    i = self.mem_version_counters[offset]
                    self.mem_version_stacks[offset].append(i)
                    self.mem_version_counters[offset] = i + 1
                    outs.append(offset)

            elif inst.opcode == "mload":
                offset = inst.operands[0].value if isinstance(inst.operands[0], IRLiteral) else None
                if offset is not None and offset in self.mem_version_stacks:
                    inst.output = IRVariable(f"mem{offset}", version=self.mem_version_stacks[offset][-1])

        # Process dominated blocks
        for bb in self.dom.dominated[basic_block]:
            if bb == basic_block:
                continue
            self._rename_mem_ops(bb)

        # Post-action
        for offset in outs:
            self.mem_version_stacks[offset].pop()

    def _remove_degenerate_phis(self, entry: IRBasicBlock):
        """
        Remove unnecessary phi nodes.
        """
        for inst in entry.instructions.copy():
            if inst.opcode != "mphi":
                continue

            new_ops: list[IROperand] = []
            for label, op in inst.phi_operands:
                if op == inst.output:
                    continue
                new_ops.extend([label, op])
            
            if len(new_ops) == 0 or len(new_ops) == 2:
                entry.instructions.remove(inst)
            else:
                inst.operands = new_ops

        for bb in self.dom.dominated[entry]:
            if bb == entry:
                continue
            self._remove_degenerate_phis(bb)
