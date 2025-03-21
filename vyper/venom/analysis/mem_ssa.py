import contextlib
from typing import Optional

from vyper.venom.analysis import CFGAnalysis, DominatorTreeAnalysis, IRAnalysis, MemoryAliasAnalysis
from vyper.venom.analysis.mem_alias import MemoryLocation
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, ir_printer
from vyper.venom.effects import Effects


class MemoryAccess:
    """Base class for memory SSA nodes"""

    def __init__(self, id: int):
        self.id = id
        self.reaching_def: Optional[MemoryAccess] = None
        self.loc: Optional[MemoryLocation] = None

    @property
    def is_live_on_entry(self) -> bool:
        return self.id == 0

    @property
    def is_volatile(self) -> bool:
        return self.loc.is_volatile

    @property
    def id_str(self) -> str:
        if self.is_live_on_entry:
            return "live_on_entry"
        return f"{self.id}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.id_str})"


class MemoryDef(MemoryAccess):
    """Represents a definition of memory state"""

    def __init__(self, id: int, store_inst: IRInstruction):
        super().__init__(id)
        self.store_inst = store_inst
        self.loc = store_inst.get_write_memory_location()

class MemoryUse(MemoryAccess):
    """Represents a use of memory state"""

    def __init__(self, id: int, load_inst: IRInstruction):
        super().__init__(id)
        self.load_inst = load_inst
        self.loc = load_inst.get_read_memory_location()

class MemoryPhi(MemoryAccess):
    """Represents a phi node for memory states"""

    def __init__(self, id: int, block: IRBasicBlock):
        super().__init__(id)
        self.block = block
        self.operands: list[tuple[MemoryDef, IRBasicBlock]] = []


class MemSSA(IRAnalysis):
    """
    This pass converts memory/storage operations into Memory SSA form,
    tracking memory definitions and uses explicitly.
    """

    VALID_LOCATION_TYPES = {"memory", "storage"}

    def __init__(self, analyses_cache, function, location_type: str = "memory"):
        super().__init__(analyses_cache, function)
        if location_type not in self.VALID_LOCATION_TYPES:
            raise ValueError(f"location_type must be one of: {self.VALID_LOCATION_TYPES}")
        self.location_type = location_type
        self.load_op = "mload" if location_type == "memory" else "sload"
        self.store_op = "mstore" if location_type == "memory" else "sstore"

        # Memory SSA specific state
        self.next_id = 1  # Start from 1 since 0 will be live_on_entry
        self.live_on_entry = MemoryAccess(0)  # live_on_entry node
        self.memory_defs: dict[IRBasicBlock, list[MemoryDef]] = {}
        self.memory_uses: dict[IRBasicBlock, list[MemoryUse]] = {}
        self.memory_phis: dict[IRBasicBlock, MemoryPhi] = {}
        self.current_def: dict[IRBasicBlock, MemoryAccess] = {}
        self.inst_to_def: dict[IRInstruction, MemoryDef] = {}
        self.inst_to_use: dict[IRInstruction, MemoryUse] = {}

    def analyze(self):
        # Request required analyses
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)

        # Build initial memory SSA form
        self._build_memory_ssa()

        # Clean up unnecessary phi nodes
        self._remove_redundant_phis()

    def mark_location_volatile(self, loc: MemoryLocation) -> MemoryLocation:
        volatile_loc = self.alias.mark_volatile(loc)
        
        for bb in self.memory_defs:
            for mem_def in self.memory_defs[bb]:
                if self.alias.may_alias(mem_def.loc, loc):
                    new_loc = MemoryLocation(
                        base=mem_def.loc.base,
                        offset=mem_def.loc.offset,
                        size=mem_def.loc.size,
                        is_alloca=mem_def.loc.is_alloca,
                        is_volatile=True
                    )
                    mem_def.loc = new_loc
        
        return volatile_loc

    def get_memory_def(self, inst: IRInstruction) -> Optional[MemoryDef]:
        if inst in self.inst_to_def:
            return self.inst_to_def[inst]
        return None

    def get_memory_use(self, inst: IRInstruction) -> Optional[MemoryUse]:
        if inst in self.inst_to_use:
            return self.inst_to_use[inst]
        return None

    def _build_memory_ssa(self):
        """Build the memory SSA form for the function"""
        # Initialize entry block with liveOnEntry
        entry_block = self.dom.entry_block
        self.current_def[entry_block] = self.live_on_entry

        for bb in self.cfg.dfs_pre_walk:
            self._process_block_definitions(bb)

        # Second pass: insert phi nodes where needed
        self._insert_phi_nodes()

        # Third pass: connect uses to their reaching definitions
        self._connect_uses_to_defs()

    def _process_block_definitions(self, block: IRBasicBlock):
        """Process memory definitions and uses in a basic block"""
        for inst in block.instructions:
            # Check for memory reads
            if Effects.MEMORY in inst.get_read_effects():
                mem_use = MemoryUse(self.next_id, inst)
                self.memory_uses.setdefault(block, []).append(mem_use)
                self.inst_to_use[inst] = mem_use

            # Check for memory writes
            if Effects.MEMORY in inst.get_write_effects():
                mem_def = MemoryDef(self.next_id, inst)
                self.next_id += 1

                mem_def.reaching_def = self._get_reaching_def_for_def(block, mem_def)

                self.memory_defs.setdefault(block, []).append(mem_def)
                self.current_def[block] = mem_def
                self.inst_to_def[inst] = mem_def

    def _insert_phi_nodes(self):
        """Insert phi nodes at appropriate points in the CFG"""
        worklist = list(self.memory_defs.keys())

        while worklist:
            block = worklist.pop()
            for frontier in self.dom.dominator_frontiers[block]:
                if frontier not in self.memory_phis:
                    phi = MemoryPhi(self.next_id, frontier)
                    # Add operands from each predecessor block
                    for pred in frontier.cfg_in:
                        reaching_def = self._get_in_def(pred)
                        if reaching_def:
                            phi.operands.append((reaching_def, pred))
                    self.next_id += 1
                    self.memory_phis[frontier] = phi
                    worklist.append(frontier)

    def _connect_uses_to_defs(self):
        """Connect memory uses to their reaching definitions"""

        for bb in self.cfg.dfs_pre_walk:
            if bb in self.memory_uses:
                uses = self.memory_uses[bb]
                for use in uses:
                    use.reaching_def = self._get_reaching_def(bb, use)

    def _get_in_def(self, bb: IRBasicBlock) -> Optional[MemoryAccess]:
        """Get the cfg in memorydefinition for a block"""
        if bb in self.memory_phis:
            return self.memory_phis[bb]

        if bb in self.memory_defs and self.memory_defs[bb]:
            return self.memory_defs[bb][-1]

        if bb.cfg_in:
            # Get reaching def from immediate dominator
            idom = self.dom.immediate_dominators[bb]
            return self._get_in_def(idom) if idom else self.live_on_entry

        return self.live_on_entry

    def _get_reaching_def(self, bb: IRBasicBlock, use: MemoryUse) -> Optional[MemoryAccess]:
        """Get the reaching definition for a memory use"""
        use_idx = bb.instructions.index(use.load_inst)
        for inst in reversed(bb.instructions[:use_idx]):
            if inst in self.inst_to_def:
                return self.inst_to_def[inst]

        if bb in self.memory_phis:
            return self.memory_phis[bb]

        if bb.cfg_in:
            idom = self.dom.immediate_dominators.get(bb)
            return self._get_in_def(idom) if idom else self.live_on_entry

        return self.live_on_entry

    def _get_reaching_def_for_def(self, bb: IRBasicBlock, def_inst: MemoryDef) -> MemoryAccess:
        """Get the reaching definition for a memory definition"""
        def_idx = bb.instructions.index(def_inst.store_inst)
        def_loc = def_inst.loc

        for inst in reversed(bb.instructions[:def_idx]):
            if inst in self.inst_to_def:
                prev_def = self.inst_to_def[inst]
                if self.alias.may_alias(def_loc, prev_def.loc):
                    return prev_def

        if bb in self.memory_phis:
            phi = self.memory_phis[bb]
            for op, _ in phi.operands:
                if isinstance(op, MemoryDef) and self.alias.may_alias(def_loc, op.loc):
                    return phi

        if bb.cfg_in:
            idom = self.dom.immediate_dominators.get(bb)
            if idom:
                in_def = self._get_in_def(idom)
                # Only use the in_def if it might alias with our definition
                if isinstance(in_def, MemoryDef) and self.alias.may_alias(def_loc, in_def.loc):
                    return in_def

        return self.live_on_entry

    def _remove_redundant_phis(self):
        """Remove unnecessary phi nodes"""
        for phi in list(self.memory_phis.values()):
            if all(op[1] == phi for op in phi.operands):
                del self.memory_phis[phi.block]

    def get_clobbered_memory_access(self, access: Optional[MemoryAccess]) -> Optional[MemoryAccess]:
        if access is None or access.is_live_on_entry:
            return None

        query_loc = access.loc
        if isinstance(access, MemoryPhi):
            # For a phi, check all incoming paths
            for acc, _ in access.operands:
                clobbering = self._walk_for_clobbered_access(acc, query_loc)
                if clobbering and not clobbering.is_live_on_entry:
                    # Phi itself if any path has a clobber
                    return access
            result = self.live_on_entry
        else:
            result = (
                self._walk_for_clobbered_access(access.reaching_def, query_loc)
                or self.live_on_entry
            )

        return result

    def _walk_for_clobbered_access(
        self, current: Optional[MemoryAccess], query_loc: MemoryLocation
    ) -> Optional[MemoryAccess]:
        while current and not current.is_live_on_entry:
            if isinstance(current, MemoryDef) and self.alias.may_alias(query_loc, current.loc):
                return current
            elif isinstance(current, MemoryPhi):
                for access, _ in current.operands:
                    clobbering = self._walk_for_clobbered_access(access, query_loc)
                    if clobbering:
                        return clobbering
            current = current.reaching_def
        return None

    def get_clobbering_memory_access(self, access: MemoryAccess) -> Optional[MemoryAccess]:
        """
        Return the memory access that clobbers (overwrites) this access, if any.
        Returns None if no clobbering access is found before a use of this access's value.
        """
        if access.is_live_on_entry:
            return None

        if not isinstance(access, MemoryDef):
            return None  # Only defs can be clobbered by subsequent stores

        def_loc = access.loc
        block = access.store_inst.parent
        def_idx = block.instructions.index(access.store_inst)

        # Check remaining instructions in the same block
        for inst in block.instructions[def_idx + 1 :]:
            next_def = self.inst_to_def.get(inst)
            if next_def and self.alias.may_alias(def_loc, next_def.loc):
                return next_def
            mem_use = self.inst_to_use.get(inst)
            if mem_use and mem_use.reaching_def == access:
                return None  # Found a use of this specific def before a clobber

        # Traverse successors
        worklist = list(block.cfg_out)
        visited = {block}
        while worklist:
            succ = worklist.pop()
            if succ in visited:
                continue
            visited.add(succ)

            # Check phi nodes
            if succ in self.memory_phis:
                phi = self.memory_phis[succ]
                for op_def, pred in phi.operands:
                    if pred == block and op_def == access:
                        # This def reaches the phi, check if phi is clobbered
                        for inst in succ.instructions:
                            next_def = self.inst_to_def.get(inst)
                            if next_def and self.alias.may_alias(def_loc, next_def.loc):
                                return next_def
                            mem_use = self.inst_to_use.get(inst)
                            if mem_use and mem_use.reaching_def == access:
                                return None

            # Check instructions in successor block
            for inst in succ.instructions:
                next_def = self.inst_to_def.get(inst)
                if next_def and self.alias.may_alias(def_loc, next_def.loc):
                    return next_def
                mem_use = self.inst_to_use.get(inst)
                if mem_use and mem_use.reaching_def == access:
                    return None  # Found a use of this specific def before a clobber

            worklist.extend(succ.cfg_out)

        return None

    #
    # Printing context methods
    #
    def _post_instruction(self, inst: IRInstruction) -> str:
        s = ""
        if inst.parent in self.memory_uses:
            for use in self.memory_uses[inst.parent]:
                if use.load_inst == inst:
                    s += f"\t; use: {use.reaching_def.id_str if use.reaching_def else None}"
        if inst.parent in self.memory_defs:
            for def_ in self.memory_defs[inst.parent]:
                if def_.store_inst == inst:
                    s += f"\t; def: {def_.id_str}"

        return s

    def _pre_block(self, bb: IRBasicBlock):
        s = ""
        if bb in self.memory_phis:
            phi = self.memory_phis[bb]
            s += f"    ; phi: {phi.id_str} <- "
            s += ", ".join(f"{op[0].id_str} from @{op[1].label}" for op in phi.operands)
            s += "\n"
        return s

    @contextlib.contextmanager
    def print_context(self):
        ir_printer.set(self)
        yield
        ir_printer.set(None)
