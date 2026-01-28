from vyper.venom.passes.base_pass import IRPass
from vyper.venom.analysis import BasePtrAnalysis, LivenessAnalysis, MemoryAliasAnalysis, DFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.memory_location import MemoryLocation
import vyper.evm.address_space as addr_space
from vyper.venom.effects import Effects, to_addr_space
from vyper.venom.passes.machinery.inst_updater import InstUpdater

_NONMEM_COPY_OPCODES = ("calldatacopy", "codecopy", "dloadbytes", "returndatacopy")
_COPIES_OPCODES = ("mcopy", *_NONMEM_COPY_OPCODES)

_LOADS = {"mload": Effects.MEMORY, "sload": Effects.STORAGE, "tload": Effects.TRANSIENT}
_STORES = {"mstore": Effects.MEMORY, "sstore": Effects.STORAGE, "tstore": Effects.TRANSIENT}

class MemoryCopyElisionPass(IRPass):
    base_ptr: BasePtrAnalysis
    copies: dict[MemoryLocation, IRInstruction]
    loads: dict[Effects, dict[IRVariable, tuple[MemoryLocation, IRInstruction]]]

    def run_pass(self):
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.loads = {Effects.MEMORY: dict(), Effects.STORAGE: dict(), Effects.TRANSIENT: dict()}

        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

        # Invalidate analyses that may be affected by IR modifications
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)

    def _process_bb(self, bb: IRBasicBlock):
        self.copies = dict()
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

    def _invalidate(self, write_loc: MemoryLocation, eff: Effects):
        if not write_loc.is_fixed and Effects.MEMORY in eff:
            self.copies.clear()
        if not write_loc.is_fixed:
            self.loads[eff].clear()

        if Effects.MEMORY in eff:
            to_remove = []
            for mem_loc in self.copies.keys():
                if self.mem_alias.may_alias(mem_loc, write_loc):
                    to_remove.append(mem_loc)

            for mem_loc in to_remove:
                del self.copies[mem_loc]
        
        to_remove = []
        for var, (mem_loc, _) in self.loads[eff].items():
            if self.mem_alias.may_alias(mem_loc, write_loc):
                to_remove.append(var)

        for var in to_remove:
            del self.loads[eff][var]


    def _try_elide_copy(self, inst: IRInstruction):
        assert inst.opcode == "mcopy"
        read_loc = self.base_ptr.get_read_location(inst, addr_space.MEMORY)
        if read_loc not in self.copies:
            return
        
        previous = self.copies[read_loc]

        assert previous.opcode in _COPIES_OPCODES, previous

        inst_size, _, _ = inst.operands
        previous_size, src, _ = previous.operands
        
        if inst_size != previous_size:
            return

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
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects

