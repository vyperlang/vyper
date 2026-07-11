import dataclasses as dc
from collections import deque
from dataclasses import dataclass
from typing import Optional

import vyper.venom.effects as effects
from vyper.evm.address_space import (
    CALLDATA,
    CODE,
    DATA,
    MEMORY,
    RETURNDATA,
    STORAGE,
    TRANSIENT,
    AddrSpace,
)
from vyper.exceptions import CompilerPanic
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.memory_location import (
    Allocation,
    InstAccessOps,
    MemoryLocation,
    memory_read_ops,
    memory_write_ops,
)


@dataclass(frozen=True)
class Ptr:
    """
    class representing an offset into an Allocation
    """

    base_alloca: Allocation

    # the offset inside the allocated region
    offset: int | None = 0  # None == unknown

    def offset_by(self, offset: int | None):
        if offset is None or self.offset is None:
            return dc.replace(self, offset=None)
        return dc.replace(self, offset=self.offset + offset)

    @classmethod
    def from_alloca(cls, alloca: IRInstruction):
        return cls(Allocation(alloca))


class BasePtrAnalysis(IRAnalysis):
    """
    Analysis to get every possible base pointer for variables.
    The allocation instruction is the source of base pointer and other
    instructions (add/sub/assign/phi) are used to manipulate these base
    pointers.
    """

    var_to_mem: dict[IRVariable, set[Ptr]]
    _untracked_root_memo: dict[IRVariable, bool]
    _untracked_root_active: set[IRVariable]

    def analyze(self):
        self.var_to_mem = dict()
        self._untracked_root_memo = dict()
        self._untracked_root_active = set()
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
        opcode = inst.opcode

        # `bump` is dual-output (a_out, sum). Semantically a_out == a
        # (its first input), but we treat a_out as a *fresh* base pointer
        # marker for the allocated region so that successive bumps in the
        # FMP chain (each marking a distinct allocation) do not appear to
        # alias each other through the shared FMP dataflow. The second
        # output (advanced fmp) is a fresh SSA var used only to sequence
        # subsequent bumps/invokes and does not alias any known region.
        if opcode == "bump":
            ptr_out = inst.get_outputs()[0]
            return self._add_possible_ptrs(ptr_out, {Ptr.from_alloca(inst)})

        # `getfmp` (a read of the FMP virtual register) intentionally gets no
        # pointer facts: its output is an *untracked* base, so anything rooted
        # at it (e.g. DretDesugarPass's pack destinations) resolves to an
        # unknown-offset location and aliases conservatively -- the same
        # protection the entry-FMP param copy gives lowered IR.

        if inst.num_outputs != 1:
            return False

        if opcode in ("alloca", "dalloca"):
            return self._add_possible_ptrs(inst.output, {Ptr.from_alloca(inst)})

        elif opcode in ("add", "sub"):
            rhs, lhs = inst.operands
            lhs_ptrs = self.get_possible_ptrs(lhs) if isinstance(lhs, IRVariable) else set()
            rhs_ptrs = self.get_possible_ptrs(rhs) if isinstance(rhs, IRVariable) else set()

            out_ptrs: set[Ptr] = set()

            # Preserve exact offsets when one side is a pointer and the other
            # is a known integer literal.
            if lhs_ptrs and isinstance(rhs, IRLiteral):
                delta = rhs.value if opcode == "add" else -rhs.value
                out_ptrs.update(ptr.offset_by(delta) for ptr in lhs_ptrs)
            if opcode == "add" and rhs_ptrs and isinstance(lhs, IRLiteral):
                out_ptrs.update(ptr.offset_by(lhs.value) for ptr in rhs_ptrs)

            # Pointer arithmetic with a dynamic offset still aliases the same
            # allocation, but with unknown offset.
            if not out_ptrs:
                if lhs_ptrs and not rhs_ptrs:
                    out_ptrs.update(ptr.offset_by(None) for ptr in lhs_ptrs)
                elif opcode == "add" and rhs_ptrs and not lhs_ptrs:
                    out_ptrs.update(ptr.offset_by(None) for ptr in rhs_ptrs)

            if out_ptrs:
                return self._add_possible_ptrs(inst.output, out_ptrs)

        elif opcode == "phi":
            phi_sources = set()
            for _, var in inst.phi_operands:
                assert isinstance(var, IRVariable)  # mypy help
                var_sources = self.get_possible_ptrs(var)
                phi_sources.update(var_sources)
            return self._add_possible_ptrs(inst.output, phi_sources)

        elif opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            return self._add_possible_ptrs(inst.output, self.get_possible_ptrs(inst.operands[0]))

        return False

    def _add_possible_ptrs(self, var: IRVariable, ptrs: set[Ptr]) -> bool:
        if len(ptrs) == 0:
            return False

        # BasePtrAnalysis is normally queried after MakeSSA, where each
        # variable has one definition. Some early global passes still query
        # it before MakeSSA, where the same variable can be assigned different
        # values on different paths. Keep facts monotonic so a later
        # non-pointer assignment cannot erase a base pointer that may still
        # reach a use through another path.
        original = self.var_to_mem.get(var, set())
        new_ptrs = self._normalize_ptrs(original | ptrs)
        if new_ptrs == original:
            return False

        self.var_to_mem[var] = new_ptrs
        return True

    def _normalize_ptrs(self, ptrs: set[Ptr]) -> set[Ptr]:
        offsets_by_base: dict[Allocation, set[int | None]] = {}
        for ptr in ptrs:
            offsets_by_base.setdefault(ptr.base_alloca, set()).add(ptr.offset)

        ret: set[Ptr] = set()
        for base_alloca, offsets in offsets_by_base.items():
            if len(offsets) == 1:
                ret.add(Ptr(base_alloca, next(iter(offsets))))
            else:
                ret.add(Ptr(base_alloca, None))

        return ret

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

        offset = ops.ofst

        if isinstance(offset, IRLiteral):
            return MemoryLocation(offset.value, size=size)

        assert isinstance(offset, IRVariable)
        ptr = self.ptr_from_op(offset)
        if ptr is None:
            return MemoryLocation(offset=None, size=size)

        return MemoryLocation(offset=ptr.offset, size=size, alloca=ptr.base_alloca)

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
        elif addr_space in (CALLDATA, DATA, CODE, RETURNDATA):
            return self._get_copyable_read_location(inst, addr_space)
        else:  # pragma: nocover
            raise CompilerPanic(f"Invalid location type: {addr_space}")

    def _get_memory_write_location(self, inst) -> MemoryLocation:
        if inst.opcode == "dload":
            # TODO: use FreeVarSpace
            return MemoryLocation(offset=0, size=32)
        if inst.opcode == "invoke":
            return MemoryLocation.UNDEFINED

        if inst.get_write_effects() & effects.MEMORY == effects.EMPTY:
            return MemoryLocation.EMPTY

        return self.segment_from_ops(memory_write_ops(inst))

    def _get_memory_read_location(self, inst) -> MemoryLocation:
        if inst.opcode == "dload":
            # TODO: use FreeVarSpace
            return MemoryLocation(offset=0, size=32)
        if inst.opcode == "iload":
            return MemoryLocation.UNDEFINED
        if inst.opcode == "invoke":
            return MemoryLocation.UNDEFINED
        if inst.opcode == "ret":
            return MemoryLocation.UNDEFINED

        if inst.get_read_effects() & effects.MEMORY == effects.EMPTY:
            return MemoryLocation.EMPTY

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
        elif opcode in ("return", "stop", "sink", "selfdestruct"):
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

    def _get_copyable_read_location(self, inst, addr_space: AddrSpace) -> MemoryLocation:
        """
        Get read location for read-only/copy-from address spaces.

        These are address spaces that can be copied from but not written to
        (calldata, code, returndata, data section).
        """
        opcode = inst.opcode

        # Bulk copy: calldatacopy, codecopy, dloadbytes, returndatacopy
        # Operand layout: [size, src_offset, dst]
        if opcode == addr_space.copy_op:
            size, src_ofst, _ = inst.operands
            access_ops = InstAccessOps(ofst=src_ofst, size=size)
            return self.segment_from_ops(access_ops)

        # Single-word load (if the address space has one): calldataload, dload
        if addr_space.load_op is not None and opcode == addr_space.load_op:
            ofst = inst.operands[0]
            access_ops = InstAccessOps(ofst=ofst, size=IRLiteral(addr_space.word_scale))
            return self.segment_from_ops(access_ops)

        return MemoryLocation.EMPTY

    def get_possible_ptrs(self, var: IRVariable) -> set[Ptr]:
        return self.var_to_mem.get(var, set())

    def aliases_of_allocation(self, alloca: Allocation) -> Optional[set[IRVariable]]:
        """
        All variables that point into `alloca`.

        Returns None if any variable may point into `alloca` *and* somewhere
        else -- another allocation, or an untracked address merged in through a
        phi -- since callers that rewrite through these aliases cannot prove
        every use stays within `alloca`.
        """
        aliases: set[IRVariable] = set()

        for var, ptrs in self.var_to_mem.items():
            if len(ptrs) == 0:
                continue
            if not any(ptr.base_alloca == alloca for ptr in ptrs):
                continue
            if any(ptr.base_alloca != alloca for ptr in ptrs):
                return None
            if self.pointer_may_include_untracked_root(var):
                return None
            aliases.add(var)

        return aliases

    def pointer_may_include_untracked_root(self, var: IRVariable) -> bool:
        """
        Return True when `var` may carry an address that is not rooted in a
        tracked allocation on some phi/assign path (e.g. a param or
        calldata-derived pointer). Fails closed (True) on def cycles.
        """
        # a variable with no pointer facts at all is itself an untracked
        # root; the recursive walk assumes its callers guard on this.
        if len(self.get_possible_ptrs(var)) == 0:
            return True
        return self._pointer_may_include_untracked_root_r(var)

    def _pointer_may_include_untracked_root_r(self, var: IRVariable) -> bool:
        # A value whose facts point only into one allocation can still carry an
        # *untracked* address through phi/assign chains: an operand with no
        # pointer facts (a param, a calldata-derived pointer, ...) contributes
        # nothing to the base-pointer union, so the result looks like a clean
        # alias while actually selecting an off-allocation address on that path.
        # Such a value is not a provable alias of the allocation.
        #
        # The result is path-independent, so completed results are memoized;
        # `_untracked_root_active` only guards against on-path cycles, which
        # fail closed. A cycle-tainted result is always True, so memoizing the
        # frames that complete on a cycle path stays conservative.
        if var in self._untracked_root_memo:
            return self._untracked_root_memo[var]
        if var in self._untracked_root_active:
            return True

        self._untracked_root_active.add(var)
        ret = self._untracked_root_from_def(var)
        self._untracked_root_active.remove(var)
        self._untracked_root_memo[var] = ret
        return ret

    def _untracked_root_from_def(self, var: IRVariable) -> bool:
        # Keep this dependency lazy: importing DFGAnalysis at module scope
        # creates a cycle through vyper.venom.analysis.__init__.
        from vyper.venom.analysis.dfg import DFGAnalysis

        # requested lazily (not in analyze()): this query runs after other
        # passes may have invalidated DFGAnalysis without touching this
        # analysis, so a reference held from analyze() could be stale.
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        inst = dfg.get_producing_instruction(var)
        # every var reaching this walk has pointer facts (callers guard on
        # this), and facts are only ever attached to instruction outputs
        assert inst is not None, var

        if inst.opcode == "phi":
            for _, op in inst.phi_operands:
                assert isinstance(op, IRVariable)  # mypy help
                if len(self.get_possible_ptrs(op)) == 0:
                    return True
                if self._pointer_may_include_untracked_root_r(op):
                    return True
            return False

        if inst.opcode == "assign" and isinstance(inst.operands[0], IRVariable):
            op = inst.operands[0]
            if len(self.get_possible_ptrs(op)) == 0:
                return True
            return self._pointer_may_include_untracked_root_r(op)

        if inst.opcode in ("add", "sub"):
            for op in inst.get_input_variables():
                if len(self.get_possible_ptrs(op)) == 0:
                    continue
                if self._pointer_may_include_untracked_root_r(op):
                    return True
            return False

        # Tracked roots: the pointer originates here, so no operand can
        # smuggle in an untracked address.
        if inst.opcode in ("bump", "alloca", "dalloca"):
            return False

        # Fail closed: any other instruction that forwards pointer provenance
        # from an input is a derivation form this walk does not model (e.g. a
        # new opcode taught to `_handle_inst`), so it may also forward an
        # untracked root. Asking `instruction_derives_pointer_from` keeps this
        # walk in sync with the transfer function instead of opcode-matching.
        return any(
            self.instruction_derives_pointer_from(inst, op) for op in inst.get_input_variables()
        )

    def instruction_derives_pointer_from(self, inst: IRInstruction, var: IRVariable) -> bool:
        """
        Whether `inst` forwards pointer provenance from `var` to its output.

        This intentionally asks the analysis facts instead of matching opcodes:
        if BasePtrAnalysis learns a new pure pointer-derivation form, callers
        that walk pointer-use graphs should inherit that knowledge.
        """
        if inst.num_outputs != 1:
            return False
        if var not in inst.get_input_variables():
            return False
        if len(self.get_possible_ptrs(inst.output)) == 0:
            return False
        if inst.get_read_effects() & effects.MEMORY != effects.EMPTY:
            return False
        if inst.get_write_effects() & effects.MEMORY != effects.EMPTY:
            return False
        return True
