from vyper.evm.address_space import MEMORY
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis, MemOverwriteAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IRVariable
from vyper.venom.effects import Effects
from vyper.venom.memory_location import MemoryLocation, get_read_location, get_write_location
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
        self.updater = InstUpdater(self.dfg)

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

        self._remove_unnecessary_effects()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _remove_unnecessary_effects(self):
        self.mem_overwrite = self.analyses_cache.request_analysis(MemOverwriteAnalysis)
        for bb in self.function.get_basic_blocks():
            self._remove_unnecessary_effects_bb(bb)

    def _remove_unnecessary_effects_bb(self, bb: IRBasicBlock):
        for inst, state in self.mem_overwrite.bb_iterator(bb):
            if inst.output is not None:
                continue
            write_loc = get_write_location(inst, MEMORY)
            if write_loc == MemoryLocation.EMPTY:
                continue
            if not write_loc.is_fixed:
                continue
            overlap = [loc for loc in state if loc.completely_contains(write_loc)]
            if len(overlap) > 0:
                self.updater.nop(inst, annotation="remove unnecessery effects")

    def _process_basic_block(self, bb: IRBasicBlock):
        """Process a basic block to find and elide memory copies."""
        # Track loads that could potentially be elided
        # Maps variable -> (load_inst, src_location)
        available_loads: dict[IRVariable, tuple[IRInstruction, MemoryLocation]] = {}

        # Track mcopy operations for chain optimization
        # Maps destination location -> (mcopy_inst, src_location)
        mcopy_chain: dict[int, tuple[IRInstruction, MemoryLocation]] = {}

        # Track memory writes to invalidate loads
        for inst in bb.instructions.copy():
            if inst.opcode == "mload":
                # Track the load if it has a literal source
                if isinstance(inst.operands[0], IRLiteral) and inst.output is not None:
                    src_loc = MemoryLocation.from_operands(inst.operands[0], 32)
                    available_loads[inst.output] = (inst, src_loc)

            elif inst.opcode == "mstore":
                var, dst = inst.operands

                # Check if this is a load-store pair we can optimize
                if isinstance(var, IRVariable) and isinstance(dst, IRLiteral):
                    if var in available_loads:
                        load_inst, src_loc = available_loads[var]
                        dst_loc = MemoryLocation.from_operands(dst, 32)

                        # Check if we can elide this copy
                        if self._can_elide_copy(load_inst, inst, src_loc, dst_loc, var):
                            self._elide_copy(load_inst, inst, src_loc, dst_loc)
                            # Remove from available loads since we've processed it
                            del available_loads[var]
                            continue

                # This store invalidates any loads that may alias with the destination
                self._invalidate_aliasing_loads(available_loads, inst)
                self._invalidate_mcopy_chain(mcopy_chain, inst)

            elif inst.opcode == "mcopy":
                # Handle mcopy operations
                src_loc = get_read_location(inst, MEMORY)
                dst_loc = get_write_location(inst, MEMORY)

                # Only process if we have fixed locations
                if src_loc.is_fixed and dst_loc.is_fixed:
                    assert src_loc.offset is not None  # help mypy
                    assert dst_loc.offset is not None  # help mypy
                    # Check for redundant copy (src == dst)
                    if src_loc.offset == dst_loc.offset and src_loc.size == dst_loc.size:
                        self.updater.nop(inst, annotation="[memory copy elision - redundant mcopy]")
                        continue

                    # Check if this forms a chain with a previous copy
                    if src_loc.offset in mcopy_chain:
                        prev_inst, prev_src_loc = mcopy_chain[src_loc.offset]

                        # Check if previous instruction is a special copy (calldatacopy, etc)
                        if prev_inst.opcode in (
                            "calldatacopy",
                            "codecopy",
                            "returndatacopy",
                            "dloadbytes",
                        ):
                            # Can merge if sizes match and no hazards
                            if (
                                prev_src_loc.size == src_loc.size == dst_loc.size
                                and self._can_merge_special_copy_chain(
                                    bb, prev_inst, inst, src_loc, dst_loc
                                )
                            ):
                                # Replace mcopy with the special copy directly to final destination
                                # Need to update the destination operand
                                new_operands = list(prev_inst.operands)
                                # For these instructions, dst is the last operand
                                new_operands[-1] = inst.operands[2]  # Use mcopy's destination
                                self.updater.update(
                                    inst,
                                    prev_inst.opcode,
                                    new_operands,
                                    annotation="[memory copy elision - merged special copy]",
                                )
                                # Update chain tracking
                                del mcopy_chain[src_loc.offset]
                                # Track the new special copy in the chain for
                                # potential future merging
                                mcopy_chain[dst_loc.offset] = (inst, prev_src_loc)
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
                                size_op = inst.operands[0]
                                dst_op = inst.operands[2]
                                assert prev_src_loc.offset is not None  # help mypy
                                self.updater.update(
                                    inst, "mcopy", [size_op, IRLiteral(prev_src_loc.offset), dst_op]
                                )
                                # Update chain tracking
                                del mcopy_chain[src_loc.offset]
                                mcopy_chain[dst_loc.offset] = (inst, prev_src_loc)
                                continue

                    # Track this mcopy for potential future chaining
                    mcopy_chain[dst_loc.offset] = (inst, src_loc)

                # mcopy invalidates overlapping loads but not mcopy chains
                # (we handle mcopy chain invalidation separately)
                self._invalidate_aliasing_loads_by_inst(available_loads, inst)

            elif inst.opcode in ("calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
                # These also perform memory copies and can start chains
                dst_loc = get_write_location(inst, MEMORY)

                # Only process if we have fixed destination
                if dst_loc.is_fixed:
                    assert dst_loc.offset is not None  # help mypy
                    # Track this copy for potential future chaining with mcopy
                    # For these instructions, src_loc represents the source data location
                    # which is not a memory location but rather calldata/code/returndata
                    # We'll use a special marker to indicate the source
                    src_marker = MemoryLocation(offset=-1, size=dst_loc.size)  # Special marker
                    mcopy_chain[dst_loc.offset] = (inst, src_marker)

                self._invalidate_aliasing_loads_by_inst(available_loads, inst)
                self._invalidate_mcopy_chain(mcopy_chain, inst, exclude_current=True)

            elif self._modifies_memory(inst):
                # Conservative: clear all available loads if memory is modified
                available_loads.clear()
                mcopy_chain.clear()

            elif inst.opcode in (
                "call",
                "invoke",
                "create",
                "create2",
                "delegatecall",
                "staticcall",
            ):
                # These can modify any memory
                available_loads.clear()
                mcopy_chain.clear()

    def _can_elide_copy(
        self,
        load_inst: IRInstruction,
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
        assert load_inst.parent == store_inst.parent
        bb = load_inst.parent

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
        final_dst_loc: MemoryLocation,
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

        # Check for overlap issues
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
        # Completely redundant - remove both instructions
        # Must nop store first since it uses the load's output
        self.updater.nop(store_inst, annotation="[memory copy elision - redundant store]")
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
                write_loc = MemoryLocation.from_operands(dst, 32)
                return MemoryLocation.may_overlap(write_loc, loc)

        elif inst.opcode in ("mcopy", "calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
            assert len(inst.operands) == 3
            size_op = inst.operands[0]
            dst_op = inst.operands[2]
            if isinstance(size_op, IRLiteral) and isinstance(dst_op, IRLiteral):
                write_loc = MemoryLocation.from_operands(dst_op, size_op)
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
                read_loc = MemoryLocation.from_operands(src, 32)
                return MemoryLocation.may_overlap(read_loc, loc)

        elif inst.opcode == "mcopy":
            if len(inst.operands) >= 3:
                size_op = inst.operands[0]
                src_op = inst.operands[1]
                if isinstance(size_op, IRLiteral) and isinstance(src_op, IRLiteral):
                    read_loc = MemoryLocation.from_operands(src_op, size_op)
                    return MemoryLocation.may_overlap(read_loc, loc)

        # Conservative: assume any other memory read could alias
        return True

    def _invalidate_aliasing_loads(
        self,
        available_loads: dict[IRVariable, tuple[IRInstruction, MemoryLocation]],
        store_inst: IRInstruction,
    ):
        """Remove any tracked loads that may alias with a store."""
        if store_inst.opcode != "mstore":
            return

        _, dst = store_inst.operands
        if not isinstance(dst, IRLiteral):
            # Conservative: clear all if we can't determine the destination
            available_loads.clear()
            return

        store_loc = MemoryLocation.from_operands(dst, 32)

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
        if inst.opcode in ("mcopy", "calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
            if len(inst.operands) >= 3:
                size_op = inst.operands[0]
                dst_op = inst.operands[2]
                if isinstance(size_op, IRLiteral) and isinstance(dst_op, IRLiteral):
                    write_loc = MemoryLocation.from_operands(dst_op, size_op)

                    to_remove = []
                    for var, (_, src_loc) in available_loads.items():
                        if MemoryLocation.may_overlap(src_loc, write_loc):
                            to_remove.append(var)

                    for var in to_remove:
                        del available_loads[var]
                else:
                    # Conservative: clear all if we can't determine the destination
                    available_loads.clear()
        else:
            # Conservative: clear all for unknown memory writes
            available_loads.clear()

    def _invalidate_mcopy_chain(
        self,
        mcopy_chain: dict[int, tuple[IRInstruction, MemoryLocation]],
        inst: IRInstruction,
        exclude_current: bool = False,
    ):
        """Remove any tracked mcopy operations that may be invalidated by a memory write."""
        if inst.opcode == "mstore":
            _, dst = inst.operands
            if isinstance(dst, IRLiteral):
                write_loc = MemoryLocation.from_operands(dst, 32)

                to_remove = []
                for dst_offset, (_, src_loc) in mcopy_chain.items():
                    dst_loc = MemoryLocation(offset=dst_offset, size=src_loc.size)
                    # Invalidate if the write aliases with either source or destination
                    if MemoryLocation.may_overlap(write_loc, src_loc) or MemoryLocation.may_overlap(
                        write_loc, dst_loc
                    ):
                        to_remove.append(dst_offset)

                for offset in to_remove:
                    del mcopy_chain[offset]
            else:
                # Conservative: clear all
                mcopy_chain.clear()

        elif inst.opcode in ("mcopy", "calldatacopy", "codecopy", "returndatacopy", "dloadbytes"):
            write_loc = get_write_location(inst, MEMORY)
            if write_loc.is_fixed:
                to_remove = []
                for dst_offset, (tracked_inst, src_loc) in mcopy_chain.items():
                    # Skip if this is the current instruction and exclude_current is True
                    if exclude_current and tracked_inst is inst:
                        continue

                    dst_loc = MemoryLocation(offset=dst_offset, size=src_loc.size)
                    # Invalidate if the write aliases with either source or destination
                    # For special copies, src_loc.offset == -1, so we only check destination
                    if src_loc.offset == -1:  # Special marker for non-memory sources
                        if MemoryLocation.may_overlap(write_loc, dst_loc):
                            to_remove.append(dst_offset)
                    else:
                        if MemoryLocation.may_overlap(
                            write_loc, src_loc
                        ) or MemoryLocation.may_overlap(write_loc, dst_loc):
                            to_remove.append(dst_offset)

                for offset in to_remove:
                    del mcopy_chain[offset]
            else:
                # Conservative: clear all
                mcopy_chain.clear()
        else:
            # Conservative: clear all for unknown memory writes
            mcopy_chain.clear()
