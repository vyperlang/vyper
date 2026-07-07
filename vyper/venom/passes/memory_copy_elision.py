from collections import deque

import vyper.evm.address_space as addr_space
from vyper.utils import OrderedSet
from vyper.venom import effects
from vyper.venom.analysis import (
    BasePtrAnalysis,
    CFGAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
    LivenessAnalysis,
    MemoryAliasAnalysis,
)
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.effects import Effects, to_addr_space
from vyper.venom.memory_location import (
    Allocation,
    MemoryLocation,
    read_location_idx,
    write_location_idx,
)
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.copy_forwarding import CopyForwardingPolicy
from vyper.venom.passes.machinery.inst_updater import InstUpdater

_NONMEM_COPY_OPCODES = ("calldatacopy", "codecopy", "dloadbytes", "returndatacopy")
_COPIES_OPCODES = ("mcopy", *_NONMEM_COPY_OPCODES)

_LOADS = {"mload": Effects.MEMORY, "sload": Effects.STORAGE, "tload": Effects.TRANSIENT}
_STORES = {"mstore": Effects.MEMORY, "sstore": Effects.STORAGE, "tstore": Effects.TRANSIENT}

# Type alias for copy tracking: maps memory location to the copy instruction
CopyMap = dict[MemoryLocation, IRInstruction]
TranslateMap = dict[Allocation, tuple[Allocation, IRInstruction]]


class MemoryCopyElisionPass(IRPass):
    base_ptr: BasePtrAnalysis
    copies: CopyMap
    # Total translation: if full allocation is copied you can replace the uses
    # of the destination by uses of source
    # main:
    #   %ptr = alloca 1, 256
    #   ...
    #   %new_ptr = alloca 1, 256
    #   mcopy %new_ptr, %ptr, 256
    #   %res = mload %new_ptr <- this can be rewritten to %ptr
    #
    # this can be done as long as the source and destionation are in sync
    loads: dict[Effects, dict[IRVariable, tuple[MemoryLocation, IRInstruction]]]
    # For cross-BB analysis: maps BB -> copy state at end of BB
    bb_copies: dict[IRBasicBlock, CopyMap]
    copy_forwarding: CopyForwardingPolicy

    def run_pass(self):
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.copy_forwarding = CopyForwardingPolicy(
            self.function, self.dfg, self.base_ptr, self.mem_alias
        )
        self.loads = {Effects.MEMORY: dict(), Effects.STORAGE: dict(), Effects.TRANSIENT: dict()}
        self.bb_copies = {}

        while True:
            # Use worklist algorithm for cross-BB copy propagation
            worklist = deque(self.cfg.dfs_pre_walk)

            while len(worklist) > 0:
                bb = worklist.popleft()
                changed = self._process_bb(bb)
                if changed:
                    for succ in self.cfg.cfg_out(bb):
                        if succ not in worklist:
                            worklist.append(succ)

            self.translates = self.analyses_cache.force_analysis(TranslateAnalysis)

            change = False
            for bb in self.function.get_basic_blocks():
                change |= self._process_translation(bb)

            if not change:
                break

        # Invalidate analyses that may be affected by IR modifications
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        self.analyses_cache.invalidate_analysis(MemoryAliasAnalysis)
        self.analyses_cache.invalidate_analysis(TranslateAnalysis)

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
        return self.copy_forwarding.copies_equivalent(inst1, inst2)

    def _process_translation(self, bb: IRBasicBlock):
        change = False
        for inst in bb.instructions.copy():
            if Effects.MEMORY in inst.get_write_effects():
                change |= self._try_update_from_translates_write(inst)
            if Effects.MEMORY in inst.get_read_effects():
                change |= self._try_update_from_translates_read(inst)

        return change

    def _process_bb(self, bb: IRBasicBlock) -> bool:
        """Process a basic block, return True if copy state changed."""
        # Get incoming copy state from predecessors
        self.copies = self._merge_copies(bb)

        # Clear loads at BB boundary (loads are still per-BB only)
        for e in self.loads.values():
            e.clear()
        for inst in bb.instructions.copy():
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
                read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
                self._invalidate(write_loc, Effects.MEMORY)
                # mcopy has memmove semantics: a self-overlapping copy can
                # clobber its own source bytes, so it is not idempotent and
                # cannot be recorded as a reusable copy fact. (unknown
                # offsets conservatively count as overlapping.)
                if write_loc.is_fixed and not MemoryLocation.may_overlap(read_loc, write_loc):
                    self.copies[write_loc] = inst

            else:
                if Effects.RETURNDATA in inst.get_write_effects():
                    self._invalidate_returndata_copies()
                if Effects.MEMORY in inst.get_write_effects():
                    self._invalidate(
                        self.base_ptr.get_write_location(inst, addr_space.MEMORY), Effects.MEMORY
                    )
                if Effects.STORAGE in inst.get_write_effects():
                    self.loads[Effects.STORAGE].clear()
                if Effects.TRANSIENT in inst.get_write_effects():
                    self.loads[Effects.TRANSIENT].clear()

        # Check if state changed
        change = False
        old_copies = self.bb_copies.get(bb, None)
        if old_copies is None or old_copies != self.copies:
            self.bb_copies[bb] = self.copies.copy()
            change = True

        return change

    def _invalidate_returndata_copies(self):
        to_remove = [
            mem_loc
            for mem_loc, copy_inst in self.copies.items()
            if Effects.RETURNDATA in copy_inst.get_read_effects()
        ]
        for mem_loc in to_remove:
            del self.copies[mem_loc]

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
        src = self.copy_forwarding.copy_source(previous)
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
        if not write_loc.is_concrete and write_loc.is_fixed and write_loc == read_loc:
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
        # Only nop the store here. The load may still be needed by other
        # users. Let RemoveUnusedVariablesPass decide if the load can be
        # removed.
        self.updater.nop(inst)

    def _try_update_from_translates_read(self, inst: IRInstruction):
        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        translates = self.translates.translates
        if read_loc.is_concrete:
            return False
        if read_loc.alloca not in translates:
            return False
        return self._update_base_allocation_read(inst, read_loc, translates)

    def _update_base_allocation_read(
        self, inst: IRInstruction, read_loc: MemoryLocation, translates: TranslateMap
    ):
        if read_loc.alloca not in translates:
            return False

        if read_loc.offset is None:
            return False

        new_base = translates[read_loc.alloca][0]

        new_operand = new_base.inst.output
        if read_loc.offset != 0:
            tmp = self.updater.add_before(
                inst, "add", [new_base.inst.output, IRLiteral(read_loc.offset)]
            )
            assert tmp is not None
            new_operand = tmp  # help mypy
            self.base_ptr.new_gep(new_operand, new_base, read_loc.offset)

        idx = read_location_idx(inst)
        assert idx is not None
        new_ops = inst.operands.copy()
        new_ops[idx] = new_operand
        self.updater.update(inst, inst.opcode, new_ops)
        return True

    def _try_update_from_translates_write(self, inst: IRInstruction):
        write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
        translates = self.translates.translates
        if write_loc.is_concrete:
            return False
        if write_loc.alloca not in translates:
            return False
        return self._update_base_allocation_write(inst, write_loc, translates)

    def _update_base_allocation_write(
        self, inst: IRInstruction, write_loc: MemoryLocation, translates: TranslateMap
    ):
        if write_loc.alloca not in translates:
            return False

        if write_loc.offset is None:
            return False

        new_base = translates[write_loc.alloca][0]

        new_operand = new_base.inst.output
        if write_loc.offset != 0:
            tmp = self.updater.add_before(
                inst, "add", [new_base.inst.output, IRLiteral(write_loc.offset)]
            )
            assert tmp is not None
            new_operand = tmp  # help mypy
            self.base_ptr.new_gep(new_operand, new_base, write_loc.offset)

        idx = write_location_idx(inst)
        assert idx is not None
        new_ops = inst.operands.copy()
        new_ops[idx] = new_operand
        self.updater.update(inst, inst.opcode, new_ops)
        return True


class TranslateAnalysis(IRAnalysis):
    translates: TranslateMap
    _inst_translates: dict[IRInstruction, TranslateMap]
    bb_translates: dict[IRBasicBlock, TranslateMap]

    def analyze(self):
        self._inst_translates = dict()
        self.bb_translates = dict()
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)

        while True:
            change = False
            for bb in self.function.get_basic_blocks():
                change |= self._process_bb(bb)

            if not change:
                break

        self.translates = TranslateMap()

        checked = OrderedSet()

        for translate_map in self._inst_translates.values():
            for translate in translate_map.items():
                dst, data = translate
                src, source = data
                if dst in checked:
                    continue

                dst_vars = self.base_ptr.vars_in_allocations[dst]
                uses: OrderedSet[IRInstruction] = OrderedSet()
                all_ok = True
                for var in dst_vars:
                    possible = self.base_ptr.get_possible_ptrs(var).copy()
                    if len(possible) != 1:
                        all_ok = False
                        break
                    if possible.pop().offset is None:
                        all_ok = False
                        break
                    uses.addmany(self.dfg.get_uses(var))

                if not all_ok:
                    continue

                for use in uses:
                    if use == source:
                        continue
                    if use.get_read_effects() | use.get_write_effects() == effects.EMPTY:
                        continue

                    if dst not in self._inst_translates[use]:
                        break

                    if self._inst_translates[use][dst][0] != src:
                        break
                else:
                    if dst in self.translates:
                        assert self.translates[dst][0] == src
                    else:
                        self.translates[dst] = (src, source)

    def _process_bb(self, bb: IRBasicBlock):
        curr = self._merge_translates(bb)

        for inst in bb.instructions:
            if inst.get_read_effects() != effects.EMPTY:
                self._invalidate(curr, self.base_ptr.get_read_location(inst, addr_space.MEMORY))

            if inst.get_write_effects() != effects.EMPTY:
                self._invalidate(
                    curr, self.base_ptr.get_write_location(inst, addr_space.MEMORY), write=True
                )

            if inst.opcode == "mcopy":
                self._try_create_translate(inst, curr)

            if inst.get_read_effects() | inst.get_write_effects() != effects.EMPTY:
                self._inst_translates[inst] = curr.copy()

        old_translates = self.bb_translates.get(bb, None)
        if old_translates is None or old_translates != curr:
            self.bb_translates[bb] = curr
            return True

        return False

    def _invalidate(self, curr: TranslateMap, loc: MemoryLocation, write=False):
        if loc.is_concrete:
            curr.clear()
        else:
            to_remove_allocations = []
            for dst, data in curr.items():
                src, _ = data
                if src == loc.alloca:
                    to_remove_allocations.append(dst)
                if write and dst == loc.alloca:
                    to_remove_allocations.append(dst)

            for item in to_remove_allocations:
                del curr[item]

    def _merge_translates(self, bb: IRBasicBlock) -> TranslateMap:
        preds = list(self.cfg.cfg_in(bb))

        if len(preds) == 0:
            return TranslateMap()

        # Start with first predecessor's state
        first_pred = preds[0]
        if first_pred not in self.bb_translates:
            return {}

        result = self.bb_translates[first_pred].copy()

        # Intersect with other predecessors
        for pred in preds[1:]:
            if pred not in self.bb_translates:
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

    def _try_create_translate(self, inst: IRInstruction, curr: TranslateMap):
        assert inst.opcode == "mcopy"

        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)

        if read_loc.is_concrete or write_loc.is_concrete:
            return

        assert read_loc.alloca is not None
        assert write_loc.alloca is not None

        if read_loc.alloca.is_dynamic or write_loc.alloca.is_dynamic:
            return

        if read_loc.offset != 0 or write_loc.offset != 0:
            return

        if read_loc.size is None:
            return

        if read_loc.alloca.alloca_size != read_loc.size:
            return

        if write_loc.alloca.alloca_size != write_loc.size:
            return

        translates_to = read_loc.alloca
        if translates_to == write_loc.alloca:
            return
        while translates_to in curr:
            translates_to, _ = curr[translates_to]
        curr[write_loc.alloca] = (translates_to, inst)
