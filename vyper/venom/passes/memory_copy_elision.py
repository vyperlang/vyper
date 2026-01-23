from typing import Optional

from vyper.evm.address_space import MEMORY
from vyper.venom.analysis import (
    BasePtrAnalysis,
    CFGAnalysis,
    DFGAnalysis,
    LivenessAnalysis,
    MemOverwriteAnalysis,
)
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.memory_location import MemoryLocation
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class MemoryCopyElisionPass(IRPass):
    """
    This pass elides useless memory copies. It identifies patterns where:
    1. A value is loaded from memory and immediately stored to another location
    2. The source memory is not modified between the load and store
    3. The value loaded is not used elsewhere
    4. Intermediate mcopy operations that can be combined or eliminated

    Common patterns optimized:
    - %1 = mload src; mstore %1, dst -> mcopy 32, src, dst (or direct copy)
    - Redundant copies where src and dst are the same
    - Load-store pairs that can be eliminated entirely
    - mcopy chains: mcopy A->B followed by mcopy B->C -> mcopy A->C
    """

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.base_ptrs = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.updater = InstUpdater(self.dfg)

        # Check if msize is used anywhere - affects what optimizations are safe
        self._msize_used = any(
            inst.opcode == "msize"
            for bb in self.function.get_basic_blocks()
            for inst in bb.instructions
        )

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

        self._remove_unnecessary_effects()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _remove_unnecessary_effects(self):
        self.mem_overwrite = self.analyses_cache.request_analysis(MemOverwriteAnalysis)

        # Collect all memory read locations in the function
        # Writes to locations that are never read are dead
        all_read_locs: list[MemoryLocation] = []
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                read_loc = self.base_ptrs.get_read_location(inst, MEMORY)
                if read_loc != MemoryLocation.EMPTY:
                    all_read_locs.append(read_loc)

        for bb in self.function.get_basic_blocks():
            self._remove_unnecessary_effects_bb(bb, all_read_locs)

    def _remove_unnecessary_effects_bb(self, bb: IRBasicBlock, all_read_locs: list[MemoryLocation]):
        for inst, state in self.mem_overwrite.bb_iterator(bb):
            if inst.has_outputs:
                continue
            write_loc = self.base_ptrs.get_write_location(inst, MEMORY)
            if write_loc == MemoryLocation.EMPTY:
                continue
            if not write_loc.is_fixed:
                continue

            # Check 1: write is overwritten before being read (from MemOverwriteAnalysis)
            overlap = [loc for loc in state if loc.completely_contains(write_loc)]
            if len(overlap) > 0:
                self.updater.nop(inst, annotation="remove unnecessary effects")
                continue

            # Check 2: write location is never read anywhere in the function
            is_ever_read = any(
                MemoryLocation.may_overlap(write_loc, read_loc) for read_loc in all_read_locs
            )
            if not is_ever_read:
                self.updater.nop(inst, annotation="remove unnecessary effects")

    def _process_basic_block(self, bb: IRBasicBlock):
        """Process a basic block to find and elide memory copies."""
        # Track loads that could potentially be elided
        # Maps variable -> (load_inst, src_location)
        available_loads: dict[IRVariable, tuple[IRInstruction, MemoryLocation]] = {}

        # Track mcopy operations for chain optimization
        # Maps destination MemoryLocation -> (copy_inst, src_location, src_operand)
        # Using MemoryLocation as key correctly distinguishes different allocas
        # src_operand is preserved for chain merging (avoids generating invalid literals)
        # src_operand is None for special copies (calldatacopy etc) since they
        # don't have a memory source
        mcopy_chain: dict[
            MemoryLocation, tuple[IRInstruction, MemoryLocation]
        ] = {}

        # Track memory writes to invalidate loads
        for inst in bb.instructions.copy():
            if inst.opcode == "mload":
                assert inst.output is not None
                # Track the load if it has a literal source
                if isinstance(inst.operands[0], IRLiteral):
                    src_loc = MemoryLocation(offset=inst.operands[0].value, size=32)
                    available_loads[inst.output] = (inst, src_loc)

            elif inst.opcode == "mstore":
                var, dst = inst.operands

                # Check if this is a load-store pair we can optimize
                if isinstance(var, IRVariable) and isinstance(dst, IRLiteral):
                    if var in available_loads:
                        load_inst, src_loc = available_loads[var]
                        dst_loc = MemoryLocation(offset=dst.value, size=32)

                        # Check if we can elide this copy
                        if self._can_elide_copy(inst, src_loc, dst_loc, var):
                            self._elide_copy(load_inst, inst, src_loc, dst_loc)
                            # Remove from available loads since we've processed it
                            del available_loads[var]
                            continue

                # This store invalidates any loads that may alias with the destination
                self._invalidate_aliasing_loads(available_loads, inst)
                self._invalidate_mcopy_chain(mcopy_chain, inst)

            elif inst.opcode == "mcopy":
                # Handle mcopy operations
                src_loc = self.base_ptrs.get_read_location(inst, MEMORY)
                dst_loc = self.base_ptrs.get_write_location(inst, MEMORY)

                # Only process if we have fixed locations
                if src_loc.is_fixed and dst_loc.is_fixed:
                    # Check for redundant copy (src == dst)
                    # MemoryLocation equality checks offset, size, AND alloca
                    if src_loc == dst_loc:
                        self.updater.nop(inst, annotation="[memory copy elision - redundant mcopy]")
                        continue

                    # Check if this forms a chain with a previous copy
                    # Use MemoryLocation as key to correctly distinguish different allocas
                    if src_loc in mcopy_chain:
                        prev_inst, prev_src_loc = mcopy_chain[src_loc]

                        # Check if previous instruction is a special copy (calldatacopy, etc)
                        if prev_inst.opcode in (
                            "calldatacopy",
                            "codecopy",
                            "returndatacopy",
                            "dloadbytes",
                        ):
                            # Can merge if sizes match and no hazards
                            # prev_src_loc is a marker (offset=-1) for special copies
                            if (
                                prev_src_loc.size == src_loc.size == dst_loc.size
                                and self._can_merge_special_copy_chain(bb, prev_inst, inst, src_loc)
                            ):
                                # Replace mcopy with the special copy directly to final destination
                                # Preserve the original operands, just update destination
                                new_operands = list(prev_inst.operands)
                                # For these instructions, dst is the last operand
                                new_operands[-1] = inst.operands[2]  # Use mcopy's destination
                                self.updater.update(inst, prev_inst.opcode, new_operands)
                                # Update chain tracking - remove old entry, add new
                                # Don't nop prev_inst here - _remove_unnecessary_effects
                                # will handle it if the intermediate write is dead
                                del mcopy_chain[src_loc]
                                # Track the new special copy in the chain for
                                # potential future merging
                                mcopy_chain[dst_loc] = (inst, prev_src_loc)
                                continue
                        else:
                            # Regular mcopy chain
                            # Check if we can merge: A->B followed by B->C becomes A->C
                            if (
                                prev_src_loc.size == src_loc.size == dst_loc.size
                                and self._can_merge_mcopy_chain(
                                    bb, prev_inst, inst, prev_src_loc, src_loc, dst_loc
                                )
                            ):
                                # Update current mcopy to copy from original source
                                # Internal order is [size, src, dst]
                                # Reuse prev_inst's source operand directly - this preserves
                                # alloca pointers instead of generating invalid literals
                                prev_src_op = prev_inst.operands[1]
                                size_op = inst.operands[0]
                                dst_op = inst.operands[2]
                                self.updater.update(inst, "mcopy", [size_op, prev_src_op, dst_op])
                                # Update chain tracking - remove old entry, add new
                                # Don't nop prev_inst here - _remove_unnecessary_effects
                                # will handle it if the intermediate write is dead
                                del mcopy_chain[src_loc]
                                mcopy_chain[dst_loc] = (inst, prev_src_loc)
                                continue

                    # Track this mcopy for potential future chaining
                    # Store the source operand for later reuse in chain merging
                    mcopy_chain[dst_loc] = (inst, src_loc)

                # mcopy invalidates overlapping loads but not mcopy chains
                # (we handle mcopy chain invalidation separately)
                self._invalidate_aliasing_loads_by_inst(available_loads, inst)

            elif inst.opcode in ("calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
                # These also perform memory copies and can start chains
                dst_loc = self.base_ptrs.get_write_location(inst, MEMORY)

                # Only process if we have fixed destination
                if dst_loc.is_fixed:
                    # Track this copy for potential future chaining with mcopy
                    # For these instructions, src_loc represents the source data location
                    # which is not a memory location but rather calldata/code/returndata
                    # We'll use a special marker to indicate the source
                    src_marker = MemoryLocation(offset=-1, size=dst_loc.size)  # Special marker
                    # Store None as src_operand since special copies don't have a memory source
                    mcopy_chain[dst_loc] = (inst, src_marker)

                self._invalidate_aliasing_loads_by_inst(available_loads, inst)
                self._invalidate_mcopy_chain(mcopy_chain, inst, exclude_current=True)

            elif self._modifies_memory(inst):
                # Conservative: clear all available loads if memory is modified
                available_loads.clear()
                mcopy_chain.clear()

    def _can_elide_copy(
        self,
        store_inst: IRInstruction,
        src_loc: MemoryLocation,
        dst_loc: MemoryLocation,
        var: IRVariable,
    ) -> bool:
        """
        Check if a load-store pair can be elided.

        Conditions:
        1. The loaded value is only used by the store (no other uses)
        2. No memory writes between load and store that could alias with src
        3. The source and destination don't overlap (unless they're identical)
        """
        # Check if the loaded value is only used by the store
        uses = self.dfg.get_uses(var)
        if len(uses) != 1 or store_inst not in uses:
            return False

        # Check if src and dst are the same (redundant copy)
        if src_loc.is_fixed and dst_loc.is_fixed:
            if src_loc.offset == dst_loc.offset and src_loc.size == dst_loc.size:
                # Redundant copy - can be eliminated entirely
                return True

        return False

    def _can_merge_special_copy_chain(
        self,
        bb: IRBasicBlock,
        special_copy: IRInstruction,
        mcopy: IRInstruction,
        intermediate_loc: MemoryLocation,
    ) -> bool:
        """
        Check if a special copy (calldatacopy, etc) followed by mcopy can be merged.

        Conditions:
        1. No memory writes between the two copies that alias with intermediate location
        2. The intermediate location is not read between the copies
        """
        first_idx = bb.instructions.index(special_copy)
        second_idx = bb.instructions.index(mcopy)

        # Check for operations between the two copies
        for i in range(first_idx + 1, second_idx):
            inst = bb.instructions[i]

            # Check if intermediate location is modified
            if self._modifies_memory_at(inst, intermediate_loc):
                return False

            # Check if intermediate location is read
            if self._reads_memory_at(inst, intermediate_loc):
                return False

        return True

    def _can_merge_mcopy_chain(
        self,
        bb: IRBasicBlock,
        first_mcopy: IRInstruction,
        second_mcopy: IRInstruction,
        orig_src_loc: MemoryLocation,
        intermediate_loc: MemoryLocation,
        final_dst_loc: MemoryLocation,
    ) -> bool:
        """
        Check if two mcopy operations can be merged into one.

        Conditions:
        1. No memory writes between the two mcopies that alias with intermediate location
        2. The intermediate location is not read between the mcopies
        3. No overlap issues that would change semantics
        """
        first_idx = bb.instructions.index(first_mcopy)
        second_idx = bb.instructions.index(second_mcopy)

        # Check for operations between the two mcopies
        for i in range(first_idx + 1, second_idx):
            inst = bb.instructions[i]

            # Check if intermediate location is modified
            if self._modifies_memory_at(inst, intermediate_loc):
                return False

            # Check if intermediate location is read
            if self._reads_memory_at(inst, intermediate_loc):
                return False

            # Check if original source is modified
            if self._modifies_memory_at(inst, orig_src_loc):
                return False

        # Overlap safety
        #
        # mcopy has memmove-like semantics: it is valid for src/dst to overlap,
        # and the destination is populated from a snapshot of the source.
        #
        # If the *first* copy writes into its own source region (A -> B where
        # A overlaps B), then rewriting the second copy (B -> C) to read from A
        # can be incorrect: A may have been clobbered by the first mcopy.
        if MemoryLocation.may_overlap(orig_src_loc, intermediate_loc):
            return False

        # If final destination overlaps with original source, merging could change semantics
        if MemoryLocation.may_overlap(final_dst_loc, orig_src_loc):
            return False

        return True

    def _elide_copy(
        self,
        load_inst: IRInstruction,
        store_inst: IRInstruction,
        src_loc: MemoryLocation,
        dst_loc: MemoryLocation,
    ):
        """Elide a load-store pair by converting to a more efficient form."""
        # Check if this is a redundant copy (src == dst)
        assert src_loc.offset == dst_loc.offset and src_loc.size == dst_loc.size
        # Redundant store - always safe to remove
        self.updater.nop(store_inst, annotation="[memory copy elision - redundant store]")
        # Redundant load - only remove if msize is not used
        # (the load affects msize by touching memory at that offset)
        if not self._msize_used:
            self.updater.nop(load_inst, annotation="[memory copy elision - redundant load]")

    def _modifies_memory(self, inst: IRInstruction) -> bool:
        """Check if an instruction modifies memory."""
        write_effects = inst.get_write_effects()
        return Effects.MEMORY in write_effects or Effects.MSIZE in write_effects

    def _reads_memory(self, inst: IRInstruction) -> bool:
        """Check if an instruction reads memory."""
        read_effects = inst.get_read_effects()
        return Effects.MEMORY in read_effects

    def _modifies_memory_at(self, inst: IRInstruction, loc: MemoryLocation) -> bool:
        """Check if an instruction modifies memory at a specific location."""
        if not self._modifies_memory(inst):
            return False

        # For stores, check if they write to an aliasing location
        if inst.opcode == "mstore":
            _, dst = inst.operands
            if isinstance(dst, IRLiteral):
                write_loc = MemoryLocation(offset=dst.value, size=32)
                return MemoryLocation.may_overlap(write_loc, loc)

        elif inst.opcode in ("mcopy", "calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
            assert len(inst.operands) == 3
            size_op = inst.operands[0]
            dst_op = inst.operands[2]
            if isinstance(size_op, IRLiteral) and isinstance(dst_op, IRLiteral):
                write_loc = MemoryLocation(offset=dst_op.value, size=size_op.value)
                return MemoryLocation.may_overlap(write_loc, loc)

        # Conservative: assume any other memory write could alias
        return True

    def _reads_memory_at(self, inst: IRInstruction, loc: MemoryLocation) -> bool:
        """Check if an instruction reads memory at a specific location."""
        if not self._reads_memory(inst):
            return False

        if inst.opcode == "mload":
            src = inst.operands[0]
            if isinstance(src, IRLiteral):
                read_loc = MemoryLocation(offset=src.value, size=32)
                return MemoryLocation.may_overlap(read_loc, loc)

        elif inst.opcode == "mcopy":
            if len(inst.operands) >= 3:
                size_op = inst.operands[0]
                src_op = inst.operands[1]
                if isinstance(size_op, IRLiteral) and isinstance(src_op, IRLiteral):
                    read_loc = MemoryLocation(offset=src_op.value, size=size_op.value)
                    return MemoryLocation.may_overlap(read_loc, loc)

        # Conservative: assume any other memory read could alias
        return True

    def _invalidate_aliasing_loads(
        self,
        available_loads: dict[IRVariable, tuple[IRInstruction, MemoryLocation]],
        store_inst: IRInstruction,
    ):
        """Remove any tracked loads that may alias with a store."""
        assert store_inst.opcode == "mstore"

        _, dst = store_inst.operands
        if not isinstance(dst, IRLiteral):
            # Conservative: clear all if we can't determine the destination
            available_loads.clear()
            return

        store_loc = MemoryLocation(offset=dst.value, size=32)

        # Remove any loads that may alias with this store
        to_remove = []
        for var, (_, src_loc) in available_loads.items():
            if MemoryLocation.may_overlap(src_loc, store_loc):
                to_remove.append(var)

        for var in to_remove:
            del available_loads[var]

    def _invalidate_aliasing_loads_by_inst(
        self,
        available_loads: dict[IRVariable, tuple[IRInstruction, MemoryLocation]],
        inst: IRInstruction,
    ):
        """Remove any tracked loads that may alias with a memory-writing instruction."""
        if inst.opcode not in ("mcopy", "calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
            # Conservative: clear all for unknown memory writes
            available_loads.clear()
            return

        assert len(inst.operands) == 3
        size_op = inst.operands[0]
        dst_op = inst.operands[2]
        _offset = dst_op.value if isinstance(dst_op, IRLiteral) else None
        _size = size_op.value if isinstance(size_op, IRLiteral) else None
        write_loc = MemoryLocation(offset=_offset, size=_size)

        if not write_loc.is_fixed:
            # Conservative: clear all if we can't determine the destination
            available_loads.clear()
            return

        to_remove = []
        for var, (_, src_loc) in available_loads.items():
            if MemoryLocation.may_overlap(src_loc, write_loc):
                to_remove.append(var)

        for var in to_remove:
            del available_loads[var]

    def _invalidate_mcopy_chain(
        self,
        mcopy_chain: dict[
            MemoryLocation, tuple[IRInstruction, MemoryLocation]
        ],
        inst: IRInstruction,
        exclude_current: bool = False,
    ):
        assert inst.opcode in (
            "mstore",
            "mcopy",
            "calldatacopy",
            "codecopy",
            "returndatacopy",
            "dloadbytes",
        )

        write_loc = self.base_ptrs.get_write_location(inst, MEMORY)
        if not write_loc.is_fixed:
            # Conservative: clear all
            mcopy_chain.clear()
            return

        to_remove = []
        for dst_loc, (tracked_inst, src_loc) in mcopy_chain.items():
            # Skip if this is the current instruction and exclude_current is True
            if exclude_current and tracked_inst is inst:
                continue

            # Invalidate if the write aliases with either source or destination
            # For special copies, src_loc.offset == -1, so we only check destination
            if src_loc.offset == -1:  # Special marker for non-memory sources
                if MemoryLocation.may_overlap(write_loc, dst_loc):
                    to_remove.append(dst_loc)
            else:
                if MemoryLocation.may_overlap(write_loc, src_loc) or MemoryLocation.may_overlap(
                    write_loc, dst_loc
                ):
                    to_remove.append(dst_loc)

        for key in to_remove:
            del mcopy_chain[key]
