from typing import TYPE_CHECKING

from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.utils import OrderedSet
from vyper.venom.analysis import BasePtrAnalysis, CFGAnalysis, DFGAnalysis, ReachableAnalysis
from vyper.venom.analysis.mem_ssa import MemoryDef, mem_ssa_type_factory
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.effects import NON_MEMORY_EFFECTS, NON_STORAGE_EFFECTS, NON_TRANSIENT_EFFECTS
from vyper.venom.passes.base_pass import InstUpdater, IRPass

if TYPE_CHECKING:
    from vyper.venom.memory_location import MemoryLocation


class DeadStoreElimination(IRPass):
    """
    This pass eliminates dead stores using Memory SSA analysis.
    """

    def run_pass(self, /, addr_space: AddrSpace):
        mem_ssa_type = mem_ssa_type_factory(addr_space)
        self.addr_space = addr_space
        if addr_space == MEMORY:
            self.NON_RELATED_EFFECTS = NON_MEMORY_EFFECTS
        elif addr_space == STORAGE:
            self.NON_RELATED_EFFECTS = NON_STORAGE_EFFECTS
        elif addr_space == TRANSIENT:
            self.NON_RELATED_EFFECTS = NON_TRANSIENT_EFFECTS

        self.reachable = self.analyses_cache.request_analysis(ReachableAnalysis)

        volatiles: list[MemoryLocation] = []
        while True:
            change = False
            self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
            self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
            self.mem_ssa = self.analyses_cache.request_analysis(mem_ssa_type)
            for volatile_loc in volatiles:
                self.mem_ssa.mark_location_volatile(volatile_loc)
            volatiles = self.mem_ssa.volatiles.copy()
            self.updater = InstUpdater(self.dfg)

            # Go through all memory definitions and eliminate dead stores
            for mem_def in self.mem_ssa.get_memory_defs():
                if self._is_dead_store(mem_def):
                    change = True
                    self.updater.nop(mem_def.store_inst, annotation="[dead store elimination]")

            if not change:
                break

            self.analyses_cache.invalidate_analysis(DFGAnalysis)
            self.analyses_cache.invalidate_analysis(mem_ssa_type)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)

    def _has_uses(self, inst: IRInstruction):
        """
        Checks if the instruction's output is used in the DFG.
        """
        return any(len(self.dfg.get_uses(output)) > 0 for output in inst.get_outputs())

    def _is_memory_def_live(self, query_def: MemoryDef) -> bool:
        """
        Checks if the memory definition is live by checking if it is
        read from in any of the blocks that are reachable from the
        memory definition's block, without being clobbered by another
        memory access before read.
        """
        query_loc = query_def.loc
        worklist: OrderedSet[IRBasicBlock] = OrderedSet()

        # blocks not to visit
        visited: OrderedSet[IRBasicBlock] = OrderedSet()

        # for the first block, we start from the instruction after mem_def.inst
        next_inst_idx = query_def.inst.parent.instructions.index(query_def.inst) + 1

        # we don't add this to visited because in the case of a loop
        # (bb is reachable from itself), we want to be able to visit it again
        # starting from instruction 0.
        worklist.add(query_def.inst.parent)

        # short circuit since the empty
        # write is noop
        if query_loc.is_empty():
            return False

        # short circuit for a case where only one instruction
        # uses all of the mem location in alias set
        # from that we know the write cannot be read
        # and therefore is dead
        alias_set = self.mem_ssa.memalias.get_alias_set(query_loc)
        assert alias_set is not None
        insts = self.mem_ssa.memalias.get_all_insts(query_loc)
        if len(alias_set) == 1 and len(insts) == 1:
            return False

        # if the all the instrcution with location
        # that may alias the query loc are reads we
        # can just check if the reads are reachable
        # from query def
        some_reachable = False
        for inst in insts:
            if inst is query_def.inst:
                continue
            other_loc = self.mem_ssa.memalias.base_ptr.get_write_location(
                inst, addr_space=self.addr_space
            )
            if other_loc in alias_set:
                # there is some write so we need to handle clobers
                # so we need to go to the slow path
                break

            # the loc use is reachable from the query def
            some_reachable |= self._is_reachable_from(inst, query_def.inst)
        else:
            # there were only reads so just return if some of them where reachable
            return some_reachable

        # original slow path that handles the clobers
        # by other writes into location that may alias
        # query location
        while len(worklist) > 0:
            bb = worklist.pop()

            clobbered = False
            for inst in bb.instructions[next_inst_idx:]:
                # Check if the instruction reads from the memory location
                # If so, the memory definition is used.
                mem_use = self.mem_ssa.get_memory_use(inst)
                if mem_use is not None:
                    read_loc = mem_use.loc
                    if self.mem_ssa.memalias.may_alias(read_loc, query_loc):
                        return True

                # Check if the instruction writes to the memory location
                # and it clobbers the memory definition. In this case,
                # we continue to the next block already in the worklist.
                mem_def = self.mem_ssa.get_memory_def(inst)
                if mem_def is not None:
                    write_loc = mem_def.loc
                    if write_loc.completely_contains(query_loc):
                        clobbered = True
                        break

            # If the memory definition is clobbered, we continue to
            # the next block already in the worklist without adding
            # its offspring to the worklist.
            if clobbered:
                continue

            # Otherwise, we add the block's offsprings to the worklist.
            # for all successor blocks, start from the 0'th instruction
            next_inst_idx = 0
            outs = self.cfg.cfg_out(bb)
            for out in outs:
                if out not in visited:
                    visited.add(out)
                    worklist.add(out)

        return False

    def _is_dead_store(self, mem_def: MemoryDef) -> bool:
        """
        Checks if the memory definition is a dead store.
        """

        # Volatile memory locations are never dead stores.
        if mem_def.loc.is_volatile is True:
            return False

        # Memory locations with unknown offset or size are never dead stores.
        if not mem_def.loc.is_fixed:
            return False

        # If the instruction output is used, it is not a dead store.
        if self._has_uses(mem_def.store_inst):
            return False

        # If the instruction has other effects than writing to memory,
        # it is not a dead store.
        inst = mem_def.store_inst
        write_effects = inst.get_write_effects()
        read_effects = inst.get_read_effects()
        has_other_effects = (write_effects | read_effects) & self.NON_RELATED_EFFECTS

        if has_other_effects:
            return False

        # If the memory definition is clobbered by another memory access,
        # it is a dead store.
        return not self._is_memory_def_live(mem_def)

    def _is_reachable_from(self, inst: IRInstruction, start_inst: IRInstruction) -> bool:
        if inst.parent == start_inst.parent:
            bb = inst.parent
            start_index = bb.instructions.index(start_inst)
            index = bb.instructions.index(inst)
            return start_index < index or bb in self.reachable.reachable[bb]

        return inst.parent in self.reachable.reachable[start_inst.parent]
