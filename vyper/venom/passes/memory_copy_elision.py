from collections import deque

import vyper.evm.address_space as addr_space
from vyper.venom.analysis import (
    BasePtrAnalysis,
    CFGAnalysis,
    DFGAnalysis,
    LivenessAnalysis,
    MemoryAliasAnalysis,
)
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.effects import Effects, to_addr_space
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.machinery.inst_updater import InstUpdater

_NONMEM_COPY_OPCODES = ("calldatacopy", "codecopy", "dloadbytes", "returndatacopy")
_COPIES_OPCODES = ("mcopy", *_NONMEM_COPY_OPCODES)

_LOADS = {"mload": Effects.MEMORY, "sload": Effects.STORAGE, "tload": Effects.TRANSIENT}
_STORES = {"mstore": Effects.MEMORY, "sstore": Effects.STORAGE, "tstore": Effects.TRANSIENT}

# Type alias for copy tracking: maps memory location to the copy instruction
CopyMap = dict[MemoryLocation, IRInstruction]


class MemoryCopyElisionPass(IRPass):
    base_ptr: BasePtrAnalysis
    copies: CopyMap
    loads: dict[Effects, dict[IRVariable, tuple[MemoryLocation, IRInstruction]]]
    # For cross-BB analysis: maps BB -> copy state at end of BB
    bb_copies: dict[IRBasicBlock, CopyMap]

    def run_pass(self):
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.loads = {Effects.MEMORY: dict(), Effects.STORAGE: dict(), Effects.TRANSIENT: dict()}
        self.bb_copies = {}

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

    def _process_bb(self, bb: IRBasicBlock) -> bool:
        """Process a basic block, return True if copy state changed."""
        # Get incoming copy state from predecessors
        self.copies = self._merge_copies(bb)

        # Clear loads at BB boundary (loads are still per-BB only)
        for e in self.loads.values():
            e.clear()

        for inst in bb.instructions:
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
                self._try_elide_copy(inst)

                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                self._invalidate(write_loc, Effects.MEMORY)
                if write_loc.is_fixed:
                    self.copies[write_loc] = inst

            elif _volatile_memory(inst):
                self.copies.clear()
                self.loads[Effects.MEMORY].clear()

        # Check if state changed
        old_copies = self.bb_copies.get(bb, None)
        if old_copies is None or old_copies != self.copies:
            self.bb_copies[bb] = self.copies.copy()
            return True
        return False

    def _invalidate(self, write_loc: MemoryLocation, eff: Effects):
        if not write_loc.is_fixed and Effects.MEMORY in eff:
            self.copies.clear()
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


def _volatile_memory(inst):
    # Only clear copies when memory is written by an instruction not handled above.
    # Reading memory (sha3, log, return, revert) doesn't invalidate tracked copies.
    return Effects.MEMORY in inst.get_write_effects()
