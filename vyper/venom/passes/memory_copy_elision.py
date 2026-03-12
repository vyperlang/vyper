from collections import deque

import vyper.evm.address_space as addr_space
from vyper.venom.analysis import (
    BasePtrAnalysis,
    CFGAnalysis,
    DFGAnalysis,
    LivenessAnalysis,
    MemoryAliasAnalysis,
)
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable, IRLiteral
from vyper.venom.effects import Effects, to_addr_space
from vyper.venom.memory_location import MemoryLocation, Allocation, get_memory_read_op, update_read_location, update_write_location
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater

_NONMEM_COPY_OPCODES = ("calldatacopy", "codecopy", "dloadbytes", "returndatacopy")
_COPIES_OPCODES = ("mcopy", *_NONMEM_COPY_OPCODES)

_LOADS = {"mload": Effects.MEMORY, "sload": Effects.STORAGE, "tload": Effects.TRANSIENT}
_STORES = {"mstore": Effects.MEMORY, "sstore": Effects.STORAGE, "tstore": Effects.TRANSIENT}

# Type alias for copy tracking: maps memory location to the copy instruction
CopyMap = dict[MemoryLocation, IRInstruction]
TranslateMap = dict[Allocation, tuple[Allocation, bool]]


class MemoryCopyElisionPass(IRPass):
    base_ptr: BasePtrAnalysis
    copies: CopyMap
    total_translation: TranslateMap
    loads: dict[Effects, dict[IRVariable, tuple[MemoryLocation, IRInstruction]]]
    # For cross-BB analysis: maps BB -> copy state at end of BB
    bb_copies: dict[IRBasicBlock, CopyMap]
    bb_translates: dict[IRBasicBlock, TranslateMap]

    def run_pass(self):
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.loads = {Effects.MEMORY: dict(), Effects.STORAGE: dict(), Effects.TRANSIENT: dict()}
        self.bb_copies = {}
        self.total_translation = dict()
        self.bb_translates = dict()

        # Use worklist algorithm for cross-BB copy propagation
        worklist = deque(self.cfg.dfs_pre_walk)

        while len(worklist) > 0:
            bb = worklist.popleft()
            changed = self._process_bb(bb)
            if changed:
                for succ in self.cfg.cfg_out(bb):
                    if succ not in worklist:
                        worklist.append(succ)

        # Invalidate analyses that may be affected by IR modifications
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        self.analyses_cache.invalidate_analysis(MemoryAliasAnalysis)

    def _merge_copies(self, bb: IRBasicBlock) -> CopyMap:
        """Merge copy info from all predecessors using intersection semantics."""
        preds = list(self.cfg.cfg_in(bb))
        if len(preds) == 0:
            return {}

        # Start with first predecessor's state
        first_pred = preds[0]
        if first_pred not in self.bb_copies:
            return {}

        result = self.bb_copies[first_pred].copy()

        # Intersect with other predecessors
        for pred in preds[1:]:
            if pred not in self.bb_copies:
                # If any predecessor hasn't been processed, be conservative
                return {}
            other = self.bb_copies[pred]
            # Keep only entries that exist in both with equivalent instructions
            common_keys = result.keys() & other.keys()
            new_result = {}
            for key in common_keys:
                # Keep if instructions are equivalent (same opcode and source location)
                if self._copies_equivalent(result[key], other[key]):
                    new_result[key] = result[key]
            result = new_result

        return result

    def _copies_equivalent(self, inst1: IRInstruction, inst2: IRInstruction) -> bool:
        """Check if two copy instructions are semantically equivalent."""

        # we can assume that the write location since the copies are
        # compared if they are in the same key in the copies map
        # so this is a sanity check for that
        write_loc1 = self.base_ptr.get_write_location(inst1, addr_space.MEMORY)
        write_loc2 = self.base_ptr.get_write_location(inst2, addr_space.MEMORY)
        assert write_loc1 == write_loc2

        if inst1 is inst2:
            return True

        if inst1.opcode != inst2.opcode:
            return False

        # Verify the source OPERANDS are equivalent (not just locations).
        # This ensures we can safely use either instruction's operands after merge.
        # are_equivalent handles assign chains (e.g., %x = 0; %y = %x -> %x == %y)
        #
        # Operand layout: [size, src, dst]
        size1, src_op1, _ = inst1.operands
        size2, src_op2, _ = inst2.operands

        if not self.dfg.are_equivalent(src_op1, src_op2):
            return False
        if not self.dfg.are_equivalent(size1, size2):
            return False

        return True

    def _merge_translates(self, bb: IRBasicBlock) -> TranslateMap:
        preds = list(self.cfg.cfg_in(bb))

        if len(preds) == 0:
            return TranslateMap()
        
        # Start with first predecessor's state
        first_pred = preds[0]
        if first_pred not in self.bb_copies:
            return {}

        result = self.bb_translates[first_pred].copy()

        # Intersect with other predecessors
        for pred in preds[1:]:
            if pred not in self.bb_copies:
                # If any predecessor hasn't been processed, be conservative
                return {}
            other = self.bb_translates[pred]

            common_keys = result.keys() & other.keys()
            new_result = {}
            for key in common_keys:
                # Keep if instructions are equivalent (same opcode and source location)
                if result[key] == other[key]:
                    new_result[key] = result[key]

            result = new_result
        
        return result



    def _process_bb(self, bb: IRBasicBlock) -> bool:
        """Process a basic block, return True if copy state changed."""
        # Get incoming copy state from predecessors
        self.copies = self._merge_copies(bb)
        self.total_translation = self._merge_translates(bb)

        # Clear loads at BB boundary (loads are still per-BB only)
        for e in self.loads.values():
            e.clear()
        for inst in bb.instructions:
            if Effects.MEMORY in inst.get_write_effects():
                self._try_update_from_translates_write(inst)
            if Effects.MEMORY in inst.get_read_effects():
                self._try_update_from_translates_read(inst)

            if inst.opcode in _LOADS:
                eff = _LOADS[inst.opcode]
                space = to_addr_space(eff)
                assert space is not None
                read_loc = self.base_ptr.get_read_location(inst, addr_space=space)
                if read_loc.is_fixed:
                    self.loads[eff][inst.output] = (read_loc, inst)

            elif inst.opcode in _STORES:
                eff = _STORES[inst.opcode]
                space = to_addr_space(eff)
                assert space is not None
                write_loc = self.base_ptr.get_write_location(inst, addr_space=space)
                self._try_elide_load_store(inst, write_loc, eff)
                self._invalidate(write_loc, eff)

            elif inst.opcode in _NONMEM_COPY_OPCODES:
                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                self._invalidate(write_loc, Effects.MEMORY)
                if write_loc.is_fixed:
                    self.copies[write_loc] = inst

            elif inst.opcode == "mcopy":
                if self._try_elide_redundant_copy(inst):
                    continue

                self._try_elide_copy(inst)

                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                self._invalidate(write_loc, Effects.MEMORY)
                if write_loc.is_fixed:
                    self.copies[write_loc] = inst

                # it was not elided to some different
                # copy
                if inst.opcode == "mcopy":
                    self._try_create_translate(inst)

            elif _volatile_memory(inst):
                self._invalidate(self.base_ptr.get_write_location(inst, addr_space.MEMORY), Effects.MEMORY)

        # Check if state changed
        change = False
        old_copies = self.bb_copies.get(bb, None)
        if old_copies is None or old_copies != self.copies:
            self.bb_copies[bb] = self.copies.copy()
            change = True

        old_translates = self.bb_translates.get(bb, None)
        if old_translates is None or old_translates != self.total_translation:
            self.bb_translates[bb] = self.total_translation
            change = True

        return change

    def _invalidate(self, write_loc: MemoryLocation, eff: Effects):
        if not write_loc.is_fixed and Effects.MEMORY in eff:
            self.copies.clear()
            self.total_translation.clear()
        if not write_loc.is_fixed:
            self.loads[eff].clear()
        if Effects.MEMORY in eff:
            to_remove = []
            for mem_loc, copy_inst in self.copies.items():
                # Invalidate if the DESTINATION is clobbered
                if self.mem_alias.may_alias(mem_loc, write_loc):
                    to_remove.append(mem_loc)
                    continue
                # Also invalidate if the SOURCE of the copy is clobbered.
                # For mcopy, source is operand[1]. For calldatacopy etc.,
                # source is in a different address space (not memory), so
                # we only need to check for mcopy.
                if copy_inst.opcode == "mcopy":
                    src_loc = self.base_ptr.get_read_location(copy_inst, addr_space.MEMORY)
                    if self.mem_alias.may_alias(src_loc, write_loc):
                        to_remove.append(mem_loc)

            for mem_loc in to_remove:
                del self.copies[mem_loc]
            
            if write_loc.is_concrete:
                self.total_translation.clear()
            else:
                to_remove = []
                for dst, translate in self.total_translation.items():
                    src, temp = translate
                    if temp:
                        continue
                    if dst == write_loc.alloca or src == write_loc.alloca:
                        to_remove.append(dst)

                for item in to_remove:
                    del self.total_translation[item]


        vars_to_remove = []
        for var, (mem_loc, _) in self.loads[eff].items():
            if self.mem_alias.may_alias(mem_loc, write_loc):
                vars_to_remove.append(var)

        for var in vars_to_remove:
            del self.loads[eff][var]

    def _try_elide_copy(self, inst: IRInstruction):
        assert inst.opcode == "mcopy"
        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        if read_loc not in self.copies:
            return

        previous = self.copies[read_loc]

        assert previous.opcode in _COPIES_OPCODES, previous

        # Size matching is guaranteed by the MemoryLocation lookup above.
        # MemoryLocation includes size as part of its identity, and only
        # fixed-size copies (where size is a literal) are tracked in self.copies.
        # Variable-size copies have is_fixed=False and aren't tracked.
        _, src, _ = previous.operands

        # Traverse assign chain to get the canonical operand. This handles
        # the case where equivalent copies on different paths use different
        # variable names (e.g., %x = 0 vs %y = 0). Using the root (literal 0)
        # avoids SSA violations when the original variable isn't defined on
        # all paths to the current block.
        #
        # Safety: _traverse_assign_chain returns a value that dominates the
        # use site because _copies_equivalent only returns True when operands
        # share a common assign-chain root (via are_equivalent), and that root
        # must dominate all paths that use it.
        if isinstance(src, IRVariable):
            src = self.dfg._traverse_assign_chain(src)

        inst.opcode = previous.opcode
        inst.operands[1] = src

    def _try_elide_redundant_copy(self, inst: IRInstruction) -> bool:
        """
        Elide mcopy when destination is already known to contain the same bytes.

        This catches repeated idempotent copies such as:
          mcopy dst, src, N
          ... only reads / non-aliasing writes ...
          mcopy dst, src, N

        Reads from dst do not invalidate copy facts, so this remains valid
        as long as neither src nor dst was clobbered in between.
        """
        assert inst.opcode == "mcopy"

        write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
        previous = self.copies.get(write_loc)
        if previous is not None and self._copies_equivalent(previous, inst):
            self.updater.nop(inst)
            return True

        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        if not write_loc.is_concrete and write_loc == read_loc:
            self.updater.nop(inst)
            return True

        return False

    def _try_elide_load_store(self, inst: IRInstruction, write_loc: MemoryLocation, eff: Effects):
        val = inst.operands[0]
        if not isinstance(val, IRVariable):
            return
        if val not in self.loads[eff]:
            return
        if self.loads[eff][val][0] != write_loc:
            return
        _, load_inst = self.loads[eff][val]
        uses = self.dfg.get_uses(load_inst.output)
        if len(uses) > 1:
            return
        # Only nop the store here. The load may still be needed for MSIZE
        # side effects. Let RemoveUnusedVariablesPass decide if the load
        # can be removed (it has proper msize fence handling).
        self.updater.nop(inst)

    def _try_create_translate(self, inst: IRInstruction):
        assert inst.opcode == "mcopy"

        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)

        if read_loc.is_concrete or write_loc.is_concrete:
            return

        if read_loc.offset != 0 or write_loc.offset != 0:
            return

        if read_loc.size is None:
            return

        assert read_loc.alloca is not None
        assert write_loc.alloca is not None

        if read_loc.alloca.alloca_size != read_loc.size:
            return

        if write_loc.alloca.alloca_size != write_loc.size:
            return

        read_var_uses = self.base_ptr.vars_in_allocations[read_loc.alloca]
        uses = set()
        for var_use in read_var_uses:
            for use in self.dfg.get_uses(var_use):
                uses.add(use)

        temp_memory = len(uses) == 1
        
        translates_to = read_loc.alloca
        if translates_to == write_loc.alloca:
            return
        while translates_to in self.total_translation:
            translates_to, temp_memory = self.total_translation[translates_to]
        self.total_translation[write_loc.alloca] = (translates_to, temp_memory)

    def _try_update_from_translates_read(self, inst: IRInstruction):
        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        if read_loc.is_concrete:
            return
        if read_loc.alloca not in self.total_translation:
            return
        self._update_base_allocation_read(inst, read_loc)

    def _update_base_allocation_read(self, inst: IRInstruction, read_loc: MemoryLocation):
        if read_loc.alloca not in self.total_translation:
            return
        
        if read_loc.offset is None:
            return

        new_base = self.total_translation[read_loc.alloca][0]

        new_operand = new_base.inst.output
        if read_loc.offset != 0:
            new_operand = self.updater.add_before(inst, "gep", [new_base.inst.output, IRLiteral(read_loc.offset)])
            assert new_operand is not None
            self.base_ptr.new_gep(new_operand, new_base, read_loc.offset)

        update_read_location(inst, new_operand)

    def _try_update_from_translates_write(self, inst: IRInstruction):
        write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
        if write_loc.is_concrete:
            return
        if write_loc.alloca not in self.total_translation:
            return
        self._update_base_allocation_write(inst, write_loc)

    def _update_base_allocation_write(self, inst: IRInstruction, write_loc: MemoryLocation):
        if write_loc.alloca not in self.total_translation:
            return
        
        if write_loc.offset is None:
            return

        new_base, temp = self.total_translation[write_loc.alloca]
        
        if not temp:
            return

        new_operand = new_base.inst.output
        if write_loc.offset != 0:
            new_operand = self.updater.add_before(inst, "gep", [new_base.inst.output, IRLiteral(write_loc.offset)])
            assert new_operand is not None
            self.base_ptr.new_gep(new_operand, new_base, write_loc.offset)

        update_write_location(inst, new_operand)


def _volatile_memory(inst):
    # Only clear copies when memory is written by an instruction not handled above.
    # Reading memory (sha3, log, return, revert) doesn't invalidate tracked copies.
    return Effects.MEMORY in inst.get_write_effects()
