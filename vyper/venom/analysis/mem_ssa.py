import contextlib
import dataclasses as dc
from typing import Iterable, Optional

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DominatorTreeAnalysis, IRAnalysis
from vyper.venom.analysis.mem_alias import (
    MemoryAliasAnalysis,
    MemoryAliasAnalysisAbstract,
    StorageAliasAnalysis,
    TransientAliasAnalysis,
)
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, ir_printer
from vyper.venom.memory_location import MemoryLocation, get_read_location, get_write_location


class MemoryAccess:
    """Base class for memory SSA nodes"""

    def __init__(self, id: int):
        self.id = id
        self.reaching_def: Optional[MemoryAccess] = None
        self.loc: MemoryLocation = MemoryLocation.EMPTY

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

    def __init__(self, id: int, store_inst: IRInstruction, addr_space: AddrSpace):
        super().__init__(id)
        self.store_inst = store_inst
        self.loc = get_write_location(store_inst, addr_space)

    @property
    def inst(self):
        return self.store_inst


class MemoryUse(MemoryAccess):
    """Represents a use of memory state"""

    def __init__(self, id: int, load_inst: IRInstruction, addr_space: AddrSpace):
        super().__init__(id)
        self.load_inst = load_inst
        self.loc = get_read_location(load_inst, addr_space)

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


class MemSSAAbstract(IRAnalysis):
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

    addr_space: AddrSpace
    mem_alias_type: type[MemoryAliasAnalysisAbstract]

    def __init__(self, analyses_cache, function):
        super().__init__(analyses_cache, function)

        self.next_id = 1  # Start from 1 since 0 will be live_on_entry

        # live_on_entry node
        self.live_on_entry = LiveOnEntry(0)

        self.memory_defs: dict[IRBasicBlock, list[MemoryDef]] = {}
        self.memory_uses: dict[IRBasicBlock, list[MemoryUse]] = {}

        # merge memory states
        self.memory_phis: dict[IRBasicBlock, MemoryPhi] = {}

        self.inst_to_def: dict[IRInstruction, MemoryDef] = {}
        self.inst_to_use: dict[IRInstruction, MemoryUse] = {}

    def analyze(self):
        # Request required analyses
        self.cfg: CFGAnalysis = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom: DominatorTreeAnalysis = self.analyses_cache.request_analysis(
            DominatorTreeAnalysis
        )
        self.memalias = self.analyses_cache.request_analysis(self.mem_alias_type)

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

    def get_memory_uses(self) -> Iterable[MemoryUse]:
        return self.inst_to_use.values()

    def get_memory_defs(self) -> Iterable[MemoryDef]:
        return self.inst_to_def.values()

    def _build_memory_ssa(self):
        """Build the memory SSA form for the function"""
        # First pass: process definitions and uses
        for bb in self.cfg.dfs_pre_walk:
            self._process_block_definitions(bb)

        # Second pass: insert phi nodes where needed
        self._insert_phi_nodes()

        # Third pass: connect all memory accesses to their reaching definitions
        self._connect_uses_to_defs()
        self._connect_defs_to_defs()

    def _process_block_definitions(self, block: IRBasicBlock):
        """Process memory definitions and uses in a basic block"""
        for inst in block.instructions:
            # Check for memory reads
            if get_read_location(inst, self.addr_space) != MemoryLocation.EMPTY:
                mem_use = MemoryUse(self.next_id, inst, self.addr_space)
                self.next_id += 1
                self.memory_uses.setdefault(block, []).append(mem_use)
                self.inst_to_use[inst] = mem_use

            # Check for memory writes
            if get_write_location(inst, self.addr_space) != MemoryLocation.EMPTY:
                mem_def = MemoryDef(self.next_id, inst, self.addr_space)
                self.next_id += 1
                self.memory_defs.setdefault(block, []).append(mem_def)
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
                        reaching_def = self.get_exit_def(pred)
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

    def get_exit_def(self, bb: IRBasicBlock) -> Optional[MemoryPhiOperand]:
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

        if bb == self.dom.entry_block:
            return self.live_on_entry

        # Get reaching def from immediate dominator
        idom = self.dom.immediate_dominators.get(bb)
        return self.get_exit_def(idom) if idom else self.live_on_entry

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
            return self.get_exit_def(idom) if idom else self.live_on_entry

        return self.live_on_entry

    def _connect_defs_to_defs(self):
        for bb in self.cfg.dfs_pre_walk:
            if bb in self.memory_defs:
                for mem_def in self.memory_defs[bb]:
                    mem_def.reaching_def = self._get_reaching_def(mem_def)

    def _remove_redundant_phis(self):
        """Remove phi nodes whose arguments are all the same"""
        for phi in list(self.memory_phis.values()):
            op0 = phi.operands[0]
            if all(op[0] == op0[0] for op in phi.operands[1:]):
                del self.memory_phis[phi.block]

    def get_aliased_memory_accesses(self, access: MemoryAccess) -> OrderedSet[MemoryAccess]:
        """
        Get all memory accesses that are aliased with the provided access.
        """
        if access.is_live_on_entry:
            return OrderedSet()

        query_loc = access.loc
        return self._walk_for_aliased_access(access, query_loc, OrderedSet())

    def _walk_for_aliased_access(
        self,
        current: Optional[MemoryAccess],
        query_loc: MemoryLocation,
        visited: OrderedSet[MemoryAccess],
    ) -> OrderedSet[MemoryAccess]:
        aliased_accesses: OrderedSet[MemoryAccess] = OrderedSet()
        while current is not None:
            if current in visited:
                break
            visited.add(current)

            # If the current node is a memory definition, check if
            # it is aliased with the query location.
            if isinstance(current, MemoryDef):
                if self.memalias.may_alias(query_loc, current.loc):
                    aliased_accesses.add(current)

            # If the current node is a phi node, recursively walk
            # the operands.
            elif isinstance(current, MemoryPhi):
                for access, _ in current.operands:
                    aliased_accesses.update(
                        self._walk_for_aliased_access(access, query_loc, visited)
                    )

            # move up the definition chain
            current = current.reaching_def

        return aliased_accesses

    def get_clobbered_memory_access(self, access: MemoryAccess) -> Optional[MemoryAccess]:
        """
        Get the memory access that gets clobbered by the provided access.
        Returns None if provided the live-on-entry node, otherwise if no clobber
            is found, it will return the live-on-entry node.

        For example:
        ```
        mstore 0, ...  ; 1
        mstore 0, ...  ; 2
        mload 0        ; 2 is clobbered by this memory access

        NOTE: This function will return a MemoryPhi if there are multiple clobbering
        memory accesses. It is to be seen if we should change this behavior in the future
        to return multiple clobbering memory accesses.

        NOTE: This corresponds to getClobberingMemoryAccess(!) in LLVM's MemorySSA.h
        """
        if access.is_live_on_entry:
            return None

        clobber = self._walk_for_clobbered_access(access.reaching_def, access.loc, OrderedSet())
        return clobber or self.live_on_entry

    def _walk_for_clobbered_access(
        self,
        current: Optional[MemoryAccess],
        query_loc: MemoryLocation,
        visited: OrderedSet[MemoryAccess],
    ) -> Optional[MemoryAccess]:
        while current is not None and not current.is_live_on_entry:
            if current in visited:
                break
            visited.add(current)

            # If the current node is a memory definition, check if
            # it completely contains the query location.
            if isinstance(current, MemoryDef):
                if query_loc.completely_contains(current.loc):
                    return current

            # If the current node is a phi node, check if any of the operands
            elif isinstance(current, MemoryPhi):
                clobbering_operands = []
                for access, _ in current.operands:
                    clobber = self._walk_for_clobbered_access(access, query_loc, visited)
                    if clobber:
                        clobbering_operands.append(clobber)

                    # Return the phi node if multiple operands have clobbering accesses
                    if len(clobbering_operands) > 1:
                        return current

                # Return the single clobbering access
                if len(clobbering_operands) == 1:
                    return clobbering_operands[0]

                return None

            # move up the definition chain
            current = current.reaching_def

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
                    clobber = self.get_clobbered_memory_access(def_)
                    if clobber is not None:
                        s += f"clobber: {clobber.id_str}"

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


class MemSSA(MemSSAAbstract):
    addr_space = MEMORY
    mem_alias_type = MemoryAliasAnalysis


class StorageSSA(MemSSAAbstract):
    addr_space = STORAGE
    mem_alias_type = StorageAliasAnalysis


class TransientSSA(MemSSAAbstract):
    addr_space = TRANSIENT
    mem_alias_type = TransientAliasAnalysis


def mem_ssa_type_factory(addr_space: AddrSpace) -> type[MemSSAAbstract]:
    if addr_space == MEMORY:
        return MemSSA
    elif addr_space == STORAGE:
        return StorageSSA
    elif addr_space == TRANSIENT:
        return TransientSSA
    else:  # should never happen
        raise ValueError(f"Invalid location type: {addr_space}")
