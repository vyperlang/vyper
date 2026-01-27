from vyper.venom.passes.base_pass import IRPass
from vyper.venom.analysis import BasePtrAnalysis, MemoryAliasAnalysis, DFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.memory_location import MemoryLocation
import vyper.evm.address_space as addr_space
from vyper.venom.effects import Effects
from vyper.venom.passes.machinery.inst_updater import InstUpdater

_NONMEM_COPY_OPCODES = ("calldatacopy", "codecopy", "dloadbytes", "returndatacopy")
_COPIES_OPCODES = ("mcopy", *_NONMEM_COPY_OPCODES)

class MemoryCopyElisionPass(IRPass):
    base_ptr: BasePtrAnalysis
    copies: dict[MemoryLocation, IRInstruction]
    loads: dict[IRVariable, tuple[MemoryLocation, IRInstruction]]

    def run_pass(self):
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        for bb in self.function.get_basic_blocks():
            self._process_bb(bb)

    def _process_bb(self, bb: IRBasicBlock):
        self.copies = dict()
        self.loads = dict()
        for inst in bb.instructions:
            if inst.opcode == "mload":
                read_loc = self.base_ptr.get_read_location(inst, addr_space=addr_space.MEMORY)
                if read_loc.is_fixed:
                    self.loads[inst.output] = (read_loc, inst)
            elif inst.opcode == "mstore":
                write_loc = self.base_ptr.get_write_location(inst, addr_space=addr_space.MEMORY)
                self._try_elide_load_store(inst, write_loc)
                self._invalidate(write_loc)

            elif inst.opcode in _NONMEM_COPY_OPCODES:
                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                self._invalidate(write_loc)
                if write_loc.is_fixed:
                    self.copies[write_loc] =inst

            elif inst.opcode == "mcopy":
                self._try_elide_copy(inst)

                write_loc = self.base_ptr.get_write_location(inst, addr_space.MEMORY)
                self._invalidate(write_loc)
                if write_loc.is_fixed:
                    self.copies[write_loc] =inst

            elif _volatile_memory(inst):
                self.copies.clear()
                self.loads.clear()

    def _invalidate(self, write_loc: MemoryLocation):
        if not write_loc.is_fixed:
            self.copies.clear()
            self.loads.clear()

        to_remove = []
        for mem_loc in self.copies.keys():
            if self.mem_alias.may_alias(mem_loc, write_loc):
                to_remove.append(mem_loc)

        for mem_loc in to_remove:
            del self.copies[mem_loc]
        
        to_remove = []
        for var, (mem_loc, _) in self.loads.items():
            if self.mem_alias.may_alias(mem_loc, write_loc):
                to_remove.append(var)

        for var in to_remove:
            del self.loads[var]


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

    def _try_elide_load_store(self, inst: IRInstruction, write_loc: MemoryLocation):
        val = inst.operands[0]
        if not isinstance(val, IRVariable):
            return
        if val not in self.loads:
            return
        if self.loads[val][0] != write_loc:
            return
        _, load_inst = self.loads[val]
        uses = self.dfg.get_uses(load_inst.output)
        if len(uses) > 1:
            return
        self.updater.nop(inst)
        self.updater.nop(load_inst)

def _volatile_memory(inst):
    inst_effects = inst.get_read_effects() | inst.get_write_effects()
    return Effects.MEMORY in inst_effects or Effects.MSIZE in inst_effects

