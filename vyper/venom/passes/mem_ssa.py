from typing import Optional

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DominatorTreeAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass


class MemSSA(IRPass):
    """
    This pass converts memory/storage operations into Static Single Assignment (SSA) form.
    Similar to variable SSA but specifically for memory/storage operations.
    """

    VALID_LOCATION_TYPES = {"memory", "storage"}

    def __init__(self, analyses_cache, function, location_type: str = "memory"):
        """
        Initialize the pass with the location type to process.

        Args:
            analyses_cache: The analyses cache
            function: The function to process
            location_type: Either "memory" for memory or "storage" for storage
        """
        super().__init__(analyses_cache, function)
        if location_type not in self.VALID_LOCATION_TYPES:
            raise ValueError(f"location_type must be one of: {self.VALID_LOCATION_TYPES}")
        self.location_type = location_type
        self.load_op = "mload" if location_type == "memory" else "sload"
        self.store_op = "mstore" if location_type == "memory" else "sstore"
        self.phi_op = "mphi" if location_type == "memory" else "sphi"
        self.var_prefix = "mem" if location_type == "memory" else "store"

    dom: DominatorTreeAnalysis
    defs: dict[int, OrderedSet[IRBasicBlock]]  # offset -> defining blocks

    def run_pass(self):
        fn = self.function

        # Request required analyses
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.analyses_cache.request_analysis(LivenessAnalysis)

        # Add phi nodes for operations
        self._add_phi_nodes()

        # Initialize version tracking
        self.version_counters = {}  # offset -> counter
        self.version_stacks = {}  # offset -> version stack

        # Rename operations starting from entry block
        self._rename_ops(fn.entry)

        # Clean up unnecessary phi nodes
        self._remove_degenerate_phis(fn.entry)

        # Invalidate liveness analysis since we modified instructions
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _compute_defs(self):
        """
        Compute definition points (store operations) for each memory/storage offset in the function.

        Returns a mapping of offsets to the basic blocks containing their definitions.
        """
        self.defs = {}
        for bb in self.dom.dfs_walk:
            for instruction in bb.instructions:
                if instruction.opcode != self.store_op:
                    continue

                offset = self._get_offset(instruction.operands[1])
                if offset is None:
                    continue

                if offset not in self.defs:
                    self.defs[offset] = OrderedSet()
                self.defs[offset].add(bb)

    def _add_phi_nodes(self):
        """
        Add phi nodes where necessary.
        """
        self._compute_defs()
        work = {var: 0 for var in self.dom.dfs_walk}
        has_already = {var: 0 for var in self.dom.dfs_walk}
        i = 0

        for offset, d in self.defs.items():
            i += 1
            defs = list(d)
            while len(defs) > 0:
                bb = defs.pop()
                for dom in self.dom.dominator_frontiers[bb]:
                    if has_already[dom] >= i:
                        continue

                    self._place_phi(offset, dom)
                    has_already[dom] = i
                    if work[dom] < i:
                        work[dom] = i
                        defs.append(dom)

    def _place_phi(self, offset: int, basic_block: IRBasicBlock):
        """
        Place a phi node in a basic block.
        """
        args: list[IROperand] = []
        for bb in basic_block.cfg_in:
            if bb == basic_block:
                continue

            args.append(bb.label)
            args.append(IRVariable(f"{self.var_prefix}{offset}"))

        basic_block.insert_instruction(
            IRInstruction(self.phi_op, args, IRVariable(f"{self.var_prefix}{offset}")), 0
        )

    def _rename_ops(self, basic_block: IRBasicBlock):
        """
        Rename operations to maintain SSA form.
        """
        outs = []

        # Pre-action
        for inst in basic_block.instructions:
            if inst.opcode == self.store_op:
                offset = self._get_offset(inst.operands[1])
                if offset is not None:
                    self._init_version_tracking(offset)

                    i = self.version_counters[offset]
                    self.version_stacks[offset].append(i)
                    self.version_counters[offset] = i + 1
                    outs.append(offset)

            elif inst.opcode == self.load_op:
                offset = inst.operands[0].value if isinstance(inst.operands[0], IRLiteral) else None
                if offset is not None and offset in self.version_stacks:
                    inst.output = IRVariable(
                        f"{self.var_prefix}{offset}", version=self.version_stacks[offset][-1]
                    )

        # Process dominated blocks
        for bb in self.dom.dominated[basic_block]:
            if bb == basic_block:
                continue
            self._rename_ops(bb)

        # Post-action
        for offset in outs:
            self.version_stacks[offset].pop()

    def _remove_degenerate_phis(self, entry: IRBasicBlock):
        """
        Remove unnecessary phi nodes.
        """
        for inst in entry.instructions.copy():
            if inst.opcode != self.phi_op:
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

    def _get_offset(self, operand: IROperand) -> Optional[int]:
        """Extract offset value from an operand if it's a literal."""
        return operand.value if isinstance(operand, IRLiteral) else None

    def _init_version_tracking(self, offset: int):
        """Initialize version tracking for a new offset."""
        if offset not in self.version_counters:
            self.version_counters[offset] = 0
            self.version_stacks[offset] = [0]
