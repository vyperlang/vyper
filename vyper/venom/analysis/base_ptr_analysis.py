from vyper.venom.analysis import IRAnalysis, DFGAnalysis
from vyper.venom.memory_location import MemoryLocation, MemoryLocationAbstract, MemoryLocationSegment
from vyper.venom.basicblock import IRVariable, IROperand, IRInstruction, IRLiteral, IRBasicBlock, IRLabel
from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
import dataclasses as dc
from dataclasses import dataclass
from typing import Optional
from vyper.exceptions import CompilerPanic

@dataclass(frozen=True)
class BasePtr:
    source: IRInstruction
    offset: int | None
    size: int

    def __post_init__(self):
        # sanity check
        assert self.source.opcode in ("alloca", "palloca"), self.source
    
    def offset_by(self, offset: int | None):
        if offset is None or self.offset is None:
            return dc.replace(self, offset=None)
        return dc.replace(self, offset=self.offset + offset)

    def without_offset(self):
        return BasePtr(source=self.source, offset=0, size=self.size)
    
    @staticmethod
    def from_alloca(alloca_inst: IRInstruction):
        assert alloca_inst.opcode in ("alloca", "palloca"), alloca_inst
        size = alloca_inst.operands[0]
        assert isinstance(size, IRLiteral)
        return BasePtr(source=alloca_inst, offset=0, size=size.value)


class BasePtrAnalysis(IRAnalysis):
    var_to_mem: dict[IRVariable, set[BasePtr]]

    def analyze(self):
        self.var_to_mem = dict()
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        while True:
            changed = False
            for bb in self.function.get_basic_blocks():
                for inst in bb.instructions:
                    changed |= self._handle_inst(inst)

            if not changed:
                break

    def _handle_inst(self, inst: IRInstruction) -> bool:
        if inst.num_outputs != 1:
            return False

        original = self.var_to_mem.get(inst.output, set())

        opcode = inst.opcode
        if opcode in ("alloca", "palloca"):
            size = inst.operands[0]
            assert isinstance(size, IRLiteral)
            self.var_to_mem[inst.output] = set([BasePtr(source=inst, offset=0, size=size.value)])
        elif opcode == "calloca":
            size, _id, callee_label = inst.operands
            assert isinstance(size, IRLiteral)
            assert isinstance(callee_label, IRLabel)
            callee = self.function.ctx.get_function(callee_label)
            palloca = callee.allocated_args[_id.value]
            assert isinstance(palloca, IRInstruction)
            self.var_to_mem[inst.output] = set([BasePtr(source=palloca, offset=0, size=size.value)])
        elif opcode == "gep":
            assert isinstance(inst.operands[0], IRVariable), inst.parent
            offset = None
            if isinstance(inst.operands[1], IRLiteral):
                offset = inst.operands[1].value
            sources = self.get_all_posible_memory(inst.operands[0])
            self.var_to_mem[inst.output] = set(ptr.offset_by(offset) for ptr in sources)
        elif opcode == "phi":
            sources = set()
            for _, var in inst.phi_operands:
                assert isinstance(var, IRVariable) # mypy help
                var_sources = self.get_all_posible_memory(var)
                sources.update(var_sources)
            self.var_to_mem[inst.output] = sources
        elif opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            self.var_to_mem[inst.output] = self.get_all_posible_memory(inst.operands[0])

        return original != self.var_to_mem.get(inst.output, set())


    def base_ptr_from_op(self, op: IROperand) -> Optional[BasePtr]:
        if not isinstance(op, IRVariable):
            return None
        item = self.var_to_mem.get(op, set()).copy()
        if len(item) == 1:
            return item.pop()
        return None 
    
    def from_operands(
        self, offset: IROperand | int, size: IROperand | int
    ) -> MemoryLocation:
        if isinstance(size, IRLiteral):
            _size = size.value
        elif isinstance(size, IRVariable):
            _size = None
        elif isinstance(size, int):
            _size = size
        else:  # pragma: nocover
            raise CompilerPanic(f"invalid size: {size} ({type(size)})")

        if isinstance(offset, IRLiteral):
            return MemoryLocationSegment(offset.value, size=_size)
        elif isinstance(offset, IRVariable):
            base_ptr = self.base_ptr_from_op(offset)
            if base_ptr is None:
                return MemoryLocationSegment(offset=None, size=_size)
            else:
                segment = MemoryLocationSegment(offset=base_ptr.offset, size=_size)
                return MemoryLocationAbstract(source=base_ptr.source, maximum_size=base_ptr.size, segment=segment)
        else:  # pragma: nocover
            raise CompilerPanic(f"invalid offset: {offset} ({type(offset)})")

    def get_write_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        """Extract memory location info from an instruction"""
        if addr_space == MEMORY:
            return self._get_memory_write_location(inst)
        elif addr_space in (STORAGE, TRANSIENT):
            return self._get_storage_write_location(inst, addr_space)
        else:  # pragma: nocover
            raise CompilerPanic(f"Invalid location type: {addr_space}")


    def get_read_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        """Extract memory location info from an instruction"""
        if addr_space == MEMORY:
            return self._get_memory_read_location(inst)
        elif addr_space in (STORAGE, TRANSIENT):
            return self._get_storage_read_location(inst, addr_space)
        else:  # pragma: nocover
            raise CompilerPanic(f"Invalid location type: {addr_space}")


    def _get_memory_write_location(self, inst) -> MemoryLocation:
        opcode = inst.opcode
        if opcode == "mstore":
            dst = inst.operands[1]
            return self.from_operands(dst, MEMORY.word_scale)
        elif opcode == "mload":
            return MemoryLocation.EMPTY
        elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
            size, _, dst = inst.operands
            return self.from_operands(dst, size)
        elif opcode == "dload":
            return MemoryLocationSegment(offset=0, size=32)
        elif opcode == "sha3_64":
            return MemoryLocationSegment(offset=0, size=64)
        elif opcode == "invoke":
            return MemoryLocation.UNDEFINED
        elif opcode == "call":
            size, dst, _, _, _, _, _ = inst.operands
            return self.from_operands(dst, size)
        elif opcode in ("delegatecall", "staticcall"):
            size, dst, _, _, _, _ = inst.operands
            return self.from_operands(dst, size)
        elif opcode == "extcodecopy":
            size, _, dst, _ = inst.operands
            return self.from_operands(dst, size)

        return MemoryLocationSegment.EMPTY


    def _get_memory_read_location(self, inst) -> MemoryLocation:
        opcode = inst.opcode
        if opcode == "mstore":
            return MemoryLocationSegment.EMPTY
        elif opcode == "mload":
            return self.from_operands(inst.operands[0], MEMORY.word_scale)
        elif opcode == "mcopy":
            size, src, _ = inst.operands
            return self.from_operands(src, size)
        elif opcode == "dload":
            return MemoryLocationSegment(offset=0, size=32)
        elif opcode == "invoke":
            return MemoryLocation.UNDEFINED
        elif opcode == "call":
            _, _, size, dst, _, _, _ = inst.operands
            return self.from_operands(dst, size)
        elif opcode in ("delegatecall", "staticcall"):
            _, _, size, dst, _, _ = inst.operands
            return self.from_operands(dst, size)
        elif opcode == "return":
            size, src = inst.operands
            return self.from_operands(src, size)
        elif opcode == "create":
            size, src, _value = inst.operands
            return self.from_operands(src, size)
        elif opcode == "create2":
            _salt, size, src, _value = inst.operands
            return self.from_operands(src, size)
        elif opcode == "sha3":
            size, offset = inst.operands
            return self.from_operands(offset, size)
        elif opcode == "sha3_64":
            return MemoryLocationSegment(offset=0, size=64)
        elif opcode == "log":
            size, src = inst.operands[-2:]
            return self.from_operands(src, size)
        elif opcode == "revert":
            size, src = inst.operands
            return self.from_operands(src, size)

        return MemoryLocationSegment.EMPTY


    def _get_storage_write_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        opcode = inst.opcode
        if opcode == addr_space.store_op:
            dst = inst.operands[1]
            return self.from_operands(dst, addr_space.word_scale)
        elif opcode == addr_space.load_op:
            return MemoryLocation.EMPTY
        elif opcode in ("call", "delegatecall", "staticcall"):
            return MemoryLocation.UNDEFINED
        elif opcode == "invoke":
            return MemoryLocation.UNDEFINED
        elif opcode in ("create", "create2"):
            return MemoryLocation.UNDEFINED

        return MemoryLocation.EMPTY


    def _get_storage_read_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        opcode = inst.opcode
        if opcode == addr_space.store_op:
            return MemoryLocation.EMPTY
        elif opcode == addr_space.load_op:
            return self.from_operands(
                inst.operands[0], addr_space.word_scale
            )
        elif opcode in ("call", "delegatecall", "staticcall"):
            return MemoryLocation.UNDEFINED
        elif opcode == "invoke":
            return MemoryLocation.UNDEFINED
        elif opcode in ("create", "create2"):
            return MemoryLocation.UNDEFINED
        elif opcode in ("return", "stop", "sink"):
            # these opcodes terminate execution and commit to (persistent)
            # storage, resulting in storage writes escaping our control.
            # returning `MemoryLocation.UNDEFINED` represents "future" reads
            # which could happen in the next program invocation.
            # while not a "true" read, this case makes the code in DSE simpler.
            return MemoryLocation.UNDEFINED
        elif opcode == "ret":
            # `ret` escapes our control and returns execution to the
            # caller function. to be conservative, we model these as
            # "future" reads which could happen in the caller.
            # while not a "true" read, this case makes the code in DSE simpler.
            return MemoryLocation.UNDEFINED

        return MemoryLocation.EMPTY
    
    def get_all_posible_memory(self, var: IRVariable) -> set[BasePtr]:
        return self.var_to_mem.get(var, set())
