import dataclasses as dc
from collections import deque
from dataclasses import dataclass
from functools import cached_property
from typing import Optional

import vyper.venom.effects as effects
from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT, AddrSpace
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.memory_location import (
    InstAccessOps,
    MemoryLocation,
    MemoryLocationAbstract,
    MemoryLocationSegment,
    memory_read_ops,
    memory_write_ops,
)


# can be thought of thin wrapper around alloca
# class Allocation
@dataclass(frozen=True)
class BasePtr:
    source: IRInstruction  # the alloca instruction

    def __post_init__(self):
        # sanity check
        assert self.source.opcode in ("alloca", "palloca"), self.source

    @property
    def is_base_ptr(self):
        return True

    @cached_property
    def source_size(self) -> IRLiteral:
        size = self.source.operands[0]
        assert isinstance(size, IRLiteral)
        return size

    @classmethod
    def from_alloca(cls, alloca_inst: IRInstruction):
        return cls(source=alloca_inst)


# don't inherit from BasePtr, instead compose .allocation inside of Ptr
@dataclass(frozen=True)
class Ptr(BasePtr):
    offset: int | None = 0  # None == unknown

    def offset_by(self, offset: int | None):
        if offset is None or self.offset is None:
            return dc.replace(self, offset=None)
        return dc.replace(self, offset=self.offset + offset)

    # (not sure if this will be useful)
    @property
    def is_base_ptr(self):
        return self.offset == 0

    @classmethod
    def from_base_ptr(cls, base_ptr: BasePtr):
        return cls(base_ptr.source, offset=0)

    # TODO: dead? or useful
    def get_base_ptr(self):
        return BasePtr(source=self.source)


class BasePtrAnalysis(IRAnalysis):
    """
    Analysis to get every possible base pointer for variables.
    The alloca/palloca are sources of base pointer and other instruction
    (gep/assign/calloca) are used to manipulate these base pointers
    """

    var_to_mem: dict[IRVariable, set[Ptr]]

    def analyze(self):
        self.var_to_mem = dict()
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        worklist = deque(self.cfg.dfs_pre_walk)

        while len(worklist) > 0:
            bb: IRBasicBlock = worklist.popleft()

            changed = False
            for inst in bb.instructions:
                changed |= self._handle_inst(inst)

            if changed:
                for succ in self.cfg.cfg_out(bb):
                    worklist.append(succ)

    def _handle_inst(self, inst: IRInstruction) -> bool:
        if inst.num_outputs != 1:
            return False

        original = self.var_to_mem.get(inst.output, set())

        opcode = inst.opcode
        if opcode in ("alloca", "palloca"):
            self.var_to_mem[inst.output] = set([Ptr.from_alloca(inst)])

        elif opcode == "calloca":
            size, _id, callee_label = inst.operands
            assert isinstance(size, IRLiteral)
            assert isinstance(callee_label, IRLabel)
            callee = self.function.ctx.get_function(callee_label)
            palloca = callee.allocated_args[_id.value]
            assert isinstance(palloca, IRInstruction)
            self.var_to_mem[inst.output] = set([Ptr.from_alloca(palloca)])

        elif opcode == "gep":
            assert isinstance(inst.operands[0], IRVariable), inst.parent
            offset = None
            if isinstance(inst.operands[1], IRLiteral):
                offset = inst.operands[1].value
            ptrs = self.get_possible_ptrs(inst.operands[0])
            self.var_to_mem[inst.output] = set(ptr.offset_by(offset) for ptr in ptrs)

        elif opcode == "phi":
            phi_sources = set()
            for _, var in inst.phi_operands:
                assert isinstance(var, IRVariable)  # mypy help
                var_sources = self.get_possible_ptrs(var)
                phi_sources.update(var_sources)
            self.var_to_mem[inst.output] = phi_sources

        elif opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            self.var_to_mem[inst.output] = self.get_possible_ptrs(inst.operands[0])

        return original != self.var_to_mem.get(inst.output, set())

    # return Ptr if there is exactly one known source for the op
    # otherwise (e.g. could return multiple sources), return None
    def ptr_from_op(self, op: IROperand) -> Optional[Ptr]:
        if not isinstance(op, IRVariable):
            return None
        ptrs = self.get_possible_ptrs(op)
        if len(ptrs) == 1:
            return next(iter(ptrs))
        return None

    def segment_from_ops(self, ops: InstAccessOps) -> MemoryLocation:
        size: Optional[int]

        if isinstance(ops.size, IRLiteral):
            size = ops.size.value
        elif isinstance(ops.size, IRVariable) or ops.size is None:
            size = None
        else:  # pragma: nocover
            raise CompilerPanic(f"invalid size: {ops} ({type(size)})")

        if size == 0:
            # optimization(!)
            return MemoryLocation.EMPTY

        offset = ops.ofst

        if isinstance(offset, IRLiteral):
            return MemoryLocationSegment(offset.value, size=size)

        assert isinstance(offset, IRVariable)
        base_ptr = self.ptr_from_op(offset)
        if base_ptr is not None:
            return MemoryLocationAbstract(
                source=base_ptr.source,
                segment=MemoryLocationSegment(offset=base_ptr.offset, size=size),
            )
        return MemoryLocationSegment(offset=None, size=size)

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
        if inst.opcode == "dload":
            return MemoryLocationSegment(offset=0, size=32)
        if inst.opcode == "invoke":
            return MemoryLocation.UNDEFINED

        if inst.get_write_effects() & effects.MEMORY == effects.EMPTY:
            return MemoryLocationSegment.EMPTY

        return self.segment_from_ops(memory_write_ops(inst))

    def _get_memory_read_location(self, inst) -> MemoryLocation:
        if inst.opcode == "dload":
            return MemoryLocationSegment(offset=0, size=32)
        if inst.opcode == "invoke":
            return MemoryLocation.UNDEFINED

        if inst.get_read_effects() & effects.MEMORY == effects.EMPTY:
            return MemoryLocationSegment.EMPTY

        return self.segment_from_ops(memory_read_ops(inst))

    # REVIEW: this should be refactored too, like get_storage_read_location
    # and get_storage_write_location
    def _get_storage_write_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        opcode = inst.opcode
        if opcode == addr_space.store_op:
            dst = inst.operands[1]
            access_ops = InstAccessOps(ofst=dst, size=IRLiteral(addr_space.word_scale))
            return self.segment_from_ops(access_ops)
        elif opcode in ("call", "delegatecall", "staticcall"):
            return MemoryLocation.UNDEFINED
        elif opcode == "invoke":
            return MemoryLocation.UNDEFINED
        elif opcode in ("create", "create2"):
            return MemoryLocation.UNDEFINED

        # TODO: add sanity check that the inst has no write effects in this addr_space
        return MemoryLocation.EMPTY

    # REVIEW: should be in MemoryLocation -- does not use base ptr analysis
    def _get_storage_read_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        opcode = inst.opcode
        if opcode == addr_space.load_op:
            ofst = inst.operands[0]
            access_ops = InstAccessOps(ofst=ofst, size=IRLiteral(addr_space.word_scale))
            return self.segment_from_ops(access_ops)
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

        # TODO: add sanity check that the inst has no read effects in this addr_space
        return MemoryLocation.EMPTY

    def get_possible_ptrs(self, var: IRVariable) -> set[Ptr]:
        return self.var_to_mem.get(var, set())
