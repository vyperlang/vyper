import contextlib
import dataclasses as dc
from typing import Optional

from vyper.venom.analysis import CFGAnalysis, DominatorTreeAnalysis, IRAnalysis, MemoryAliasAnalysis
from vyper.venom.analysis.mem_alias import MemoryLocation
from vyper.venom.basicblock import EMPTY_MEMORY_ACCESS, IRBasicBlock, IRInstruction, ir_printer
from vyper.venom.effects import Effects


class MemoryAccess:
    """Base class for memory SSA nodes"""

    def __init__(self, id: int):
        self.id = id
        self.reaching_def: Optional[MemoryAccess] = None
        self.loc: MemoryLocation = EMPTY_MEMORY_ACCESS

    @property
    def is_live_on_entry(self) -> bool:
        return self.id == 0

    @property
    def inst(self) -> IRInstruction:
        raise NotImplementedError(f"{type(self)} does not have an inst!")

    @property
    def is_volatile(self) -> bool:
        """
        Indicates whether this memory access is volatile.

        A volatile memory access means the memory location can be accessed
        or modified in ways that might not be tracked by the SSA analysis.
        This is used to handle memory locations that might be accessed
        through other function calls or other side effects.
        """
        return self.loc.is_volatile

    @property
    def id_str(self) -> str:
        if self.is_live_on_entry:
            return "live_on_entry"
        return f"{self.id}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MemoryAccess):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return self.id

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.id_str})"


class LiveOnEntry(MemoryAccess):
    """
    For type checking purposes
    """

    pass


class MemoryDef(MemoryAccess):
    """Represents a definition of memory state"""

    def __init__(self, id: int, store_inst: IRInstruction):
        super().__init__(id)
        self.store_inst = store_inst
        self.loc = store_inst.get_write_memory_location()

    @property
    def inst(self):
        return self.store_inst


class MemoryUse(MemoryAccess):
    """Represents a use of memory state"""

    def __init__(self, id: int, load_inst: IRInstruction):
        super().__init__(id)
        self.load_inst = load_inst
        self.loc = load_inst.get_read_memory_location()

    @property
    def inst(self):
        return self.load_inst


class MemoryPhi(MemoryAccess):
    """Represents a phi node for memory states"""

    def __init__(self, id: int, block: IRBasicBlock):
        super().__init__(id)
        self.block = block
        self.operands: list[tuple[MemoryPhiOperand, IRBasicBlock]] = []


# Type aliases for signatures in this module
MemoryDefOrUse = MemoryDef | MemoryUse
MemoryPhiOperand = MemoryDef | MemoryPhi | LiveOnEntry


class MemSSA(IRAnalysis):
    """
    This analysis converts memory/storage operations into Memory SSA form.
    The analysis is based on LLVM's https://llvm.org/docs/MemorySSA.html.
    Notably, the LLVM design does not partition memory into ranges.
    Rather, it keeps track of memory _states_ (each write increments a
    generation counter), and provides "walk" methods to track memory
    clobbers. This counterintuitively results in a simpler design
    and, according to LLVM, better performance.
    See https://llvm.org/docs/MemorySSA.html#design-tradeoffs.
    """

    VALID_LOCATION_TYPES = {"memory", "storage"}

    def __init__(self, analyses_cache, function, location_type: str = "memory"):
        super().__init__(analyses_cache, function)
        if location_type not in self.VALID_LOCATION_TYPES:
            raise ValueError(f"location_type must be one of: {self.VALID_LOCATION_TYPES}")
        self.location_type = location_type
        self.load_op = "mload" if location_type == "memory" else "sload"
        self.store_op = "mstore" if location_type == "memory" else "sstore"

        self.next_id = 1  # Start from 1 since 0 will be live_on_entry

        # live_on_entry node
        self.live_on_entry = LiveOnEntry(0)

        self.memory_defs: dict[IRBasicBlock, list[MemoryDef]] = {}
        self.memory_uses: dict[IRBasicBlock, list[MemoryUse]] = {}

        # merge memory states
        self.memory_phis: dict[IRBasicBlock, MemoryPhi] = {}

        # the current memory state at each basic block
        self.current_def: dict[IRBasicBlock, MemoryAccess] = {}

        self.inst_to_def: dict[IRInstruction, MemoryDef] = {}
        self.inst_to_use: dict[IRInstruction, MemoryUse] = {}

    def analyze(self):
        # Request required analyses
        self.cfg: CFGAnalysis = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom: DominatorTreeAnalysis = self.analyses_cache.request_analysis(
            DominatorTreeAnalysis
        )
        self.memalias: MemoryAliasAnalysis = self.analyses_cache.request_analysis(
            MemoryAliasAnalysis
        )

        # Build initial memory SSA form
        self._build_memory_ssa()

        # Clean up unnecessary phi nodes
        self._remove_redundant_phis()

    def mark_location_volatile(self, loc: MemoryLocation) -> MemoryLocation:
        volatile_loc = self.memalias.mark_volatile(loc)

        for bb in self.memory_defs:
            for mem_def in self.memory_defs[bb]:
                if self.memalias.may_alias(mem_def.loc, loc):
                    mem_def.loc = dc.replace(mem_def.loc, is_volatile=True)

        return volatile_loc

    def get_memory_def(self, inst: IRInstruction) -> Optional[MemoryDef]:
        return self.inst_to_def.get(inst)

    def get_memory_use(self, inst: IRInstruction) -> Optional[MemoryUse]:
        return self.inst_to_use.get(inst)

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
        effect_type = Effects.STORAGE if self.location_type == "storage" else Effects.MEMORY
        for inst in block.instructions:
            # Check for memory reads
            if effect_type in inst.get_read_effects():
                mem_use = MemoryUse(self.next_id, inst)
                self.next_id += 1
                self.memory_uses.setdefault(block, []).append(mem_use)
                self.inst_to_use[inst] = mem_use

            # Check for memory writes
            if effect_type in inst.get_write_effects():
                mem_def = MemoryDef(self.next_id, inst)
                self.next_id += 1

                mem_def.reaching_def = self._get_reaching_def(mem_def)

                self.memory_defs.setdefault(block, []).append(mem_def)
                self.current_def[block] = mem_def
                self.inst_to_def[inst] = mem_def

    def _insert_phi_nodes(self) -> None:
        """Insert phi nodes at appropriate points in the CFG"""
        worklist = list(self.memory_defs.keys())

        while worklist:
            block = worklist.pop()
            for frontier in self.dom.dominator_frontiers[block]:
                if frontier not in self.memory_phis:
                    phi = MemoryPhi(self.next_id, frontier)
                    # Add operands from each predecessor block
                    for pred in self.cfg.cfg_in(frontier):
                        reaching_def = self._get_exit_def(pred)
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
                    use.reaching_def = self._get_reaching_def(use)

    def _get_exit_def(self, bb: IRBasicBlock) -> Optional[MemoryPhiOperand]:
        """
        Get the memory def (or phi) that exits a basic block.

        This method determines which memory definition is "live"
        at the exit point of a block by:

            1. First checking if the block itself contains any
               memory definitions and returning the last one
            2. If not, checking if the block has a phi node (which
               combines definitions from multiple paths)
            3. If not, recursively checking the immediate
               dominator block
            4. If there's no dominator, returning the
               live-on-entry definition (initial state)
        """
        if bb in self.memory_defs and len(self.memory_defs[bb]) > 0:
            return self.memory_defs[bb][-1]

        if bb in self.memory_phis:
            return self.memory_phis[bb]

        if bb != self.dom.entry_block:
            # Get reaching def from immediate dominator
            idom = self.dom.immediate_dominators.get(bb)
            if idom is not None:
                return self._get_exit_def(idom)

        return self.live_on_entry

    def _get_reaching_def(self, mem_access: MemoryDefOrUse) -> Optional[MemoryAccess]:
        """
        Finds the memory definition that reaches a specific memory def or use.

        This method searches for the most recent memory definition that affects
        the given memory def or use by first looking backwards in the same basic block.
        If none is found, it checks for phi nodes in the block or returns the
        "in def" from the immediate dominator block. If there is no immediate
        dominator, it returns the live-on-entry definition.
        """
        assert isinstance(mem_access, MemoryDef) or isinstance(
            mem_access, MemoryUse
        ), "Only MemoryDef or MemoryUse is supported"

        bb = mem_access.inst.parent
        use_idx = bb.instructions.index(mem_access.inst)
        for inst in reversed(bb.instructions[:use_idx]):
            if inst in self.inst_to_def:
                return self.inst_to_def[inst]

        if bb in self.memory_phis:
            return self.memory_phis[bb]

        if self.cfg.cfg_in(bb):
            idom = self.dom.immediate_dominators.get(bb)
            return self._get_exit_def(idom) if idom else self.live_on_entry

        return self.live_on_entry

    def _remove_redundant_phis(self):
        """Remove phi nodes whose arguments are all the same"""
        for phi in list(self.memory_phis.values()):
            op0 = phi.operands[0]
            if all(op[0] == op0[0] for op in phi.operands[1:]):
                del self.memory_phis[phi.block]

    def get_clobbered_memory_access(self, access: MemoryAccess) -> Optional[MemoryAccess]:
        """
        Get the memory access that gets clobbered by the provided access.
        Returns None if provided the live-on-entry node, otherwise if no clobber
            is found, it will return the live-on-entry node.
        This can be thought of as the inverse query for `get_clobbering_memory_access`.
        For example:
        ```
        mstore 0, ...  ; 1
        mstore 0, ...  ; 2
        mload 0        ; 2 is clobbered by this memory access
        ```
        """
        if access.is_live_on_entry:
            return None

        query_loc = access.loc
        if isinstance(access, MemoryPhi):
            # For a phi, check all incoming paths
            for acc, _ in access.operands:
                clobbering = self._walk_for_clobbered_access(acc, query_loc)
                if clobbering and not clobbering.is_live_on_entry:
                    # Phi itself if any path has a clobber
                    return access
            return self.live_on_entry

        clobber = self._walk_for_clobbered_access(access.reaching_def, query_loc)
        return clobber or self.live_on_entry

    def _walk_for_clobbered_access(
        self, current: Optional[MemoryAccess], query_loc: MemoryLocation
    ) -> Optional[MemoryAccess]:
        while current and not current.is_live_on_entry:
            if isinstance(current, MemoryDef) and query_loc.completely_contains(current.loc):
                return current
            elif isinstance(current, MemoryPhi):
                for access, _ in current.operands:
                    clobbering = self._walk_for_clobbered_access(access, query_loc)
                    if clobbering is not None:
                        return clobbering
            current = current.reaching_def
        return None

    def get_clobbering_memory_access(self, access: MemoryAccess) -> Optional[MemoryAccess]:
        """
        Return the memory access that clobbers (overwrites) this access,
        if any. Returns None if no clobbering access is found before a use
        of this access's value.
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
            clobber = None
            next_def = self.inst_to_def.get(inst)
            if next_def and next_def.loc.completely_contains(def_loc):
                clobber = next_def

            # for instructions that both read and write from memory,
            # check the read first
            mem_use = self.inst_to_use.get(inst)
            if mem_use is not None:
                if self.memalias.may_alias(def_loc, mem_use.loc):
                    return None  # Found a use that reads from our memory location
            if clobber is not None:
                return clobber

        # Traverse successors
        worklist = list(self.cfg.cfg_out(block))
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
                            if next_def and next_def.loc.completely_contains(def_loc):
                                return next_def
                            mem_use = self.inst_to_use.get(inst)
                            if mem_use and mem_use.loc.completely_contains(def_loc):
                                return None  # Found a use that reads from our memory location

            # Check instructions in successor block
            for inst in succ.instructions:
                next_def = self.inst_to_def.get(inst)
                if next_def and next_def.loc.completely_contains(def_loc):
                    return next_def
                mem_use = self.inst_to_use.get(inst)
                if mem_use and mem_use.loc.completely_contains(def_loc):
                    return None  # Found a use that reads from our memory location

            worklist.extend(self.cfg.cfg_out(succ))

        return None

    #
    # Printing context methods
    #
    def _post_instruction(self, inst: IRInstruction) -> str:
        s = ""
        if inst.parent in self.memory_uses:
            for use in self.memory_uses[inst.parent]:
                if use.inst == inst:
                    s += f"\t; use: {use.reaching_def.id_str if use.reaching_def else None}"
        if inst.parent in self.memory_defs:
            for def_ in self.memory_defs[inst.parent]:
                if def_.inst == inst:
                    s += f"\t; def: {def_.id_str} "
                    s += f"({def_.reaching_def.id_str if def_.reaching_def else None}) "
                    s += f"{self.get_clobbering_memory_access(def_)}"

        return s

    def _pre_block(self, bb: IRBasicBlock) -> str:
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
        try:
            yield
        finally:
            ir_printer.set(None)
