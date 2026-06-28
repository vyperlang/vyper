from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

import vyper.evm.address_space as addr_space
from vyper.venom.analysis import (
    BasePtrAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
    MemoryAliasAnalysis,
    MemSSA,
)
from vyper.venom.analysis.readonly_memory_args import (
    MemoryParamRootResolver,
    ReadonlyMemoryArgsGlobalAnalysis,
)
from vyper.venom.basicblock import IRInstruction, IRLiteral, IROperand, IRVariable
from vyper.venom.effects import EMPTY, Effects
from vyper.venom.memory_location import Allocation, MemoryLocation, memory_read_ops
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.copy_forwarding import CopyForwardingPolicy
from vyper.venom.passes.machinery.inst_updater import InstUpdater

_POINTER_OPCODES = {"assign", "add", "sub"}
# This pass runs before concrete memory layout and has no high-water cost
# model. Huge aggregate staging copies can be cheaper to keep because they
# keep later reads in a compact frame region. Leave those to layout-aware
# optimizations.
_MAX_FORWARD_COPY_SIZE = 4096


@dataclass(frozen=True)
class _ForwardPlan:
    copy_inst: IRInstruction
    src: IROperand
    alias_rewrites: dict[IRVariable, int | None]
    direct_read_rewrites: tuple[tuple[IRInstruction, int, int], ...]
    read_sites: frozenset[IRInstruction]


class RedundantMemoryCopyForwardingPass(IRPass):
    """
    Forward reads of a fresh temp copy back to its stable source.

      %tmp = alloca N
      mcopy %tmp, %src, N
      ... readonly pointer arithmetic / mload / mcopy / sha3 from %tmp ...

    becomes reads from %src, and the staging mcopy is deleted.  This pass
    deliberately handles only local, provable readonly use-shapes.
    """

    # Needs the canonical mcopy shape formed by MemMerge/MemoryCopyElision,
    # and must run while static allocas are still abstract.
    required_predecessors = ("MemoryCopyElisionPass",)
    required_successors = ("ConcretizeMemLocPass",)

    dfg: DFGAnalysis
    domtree: DominatorTreeAnalysis
    base_ptr: BasePtrAnalysis
    mem_alias: MemoryAliasAnalysis
    mem_ssa: MemSSA
    updater: InstUpdater
    copy_forwarding: CopyForwardingPolicy
    readonly_memory_args: ReadonlyMemoryArgsGlobalAnalysis
    param_roots: MemoryParamRootResolver

    def run_pass(self):
        changed = False

        while True:
            self._prepare()
            copy_inst = self._find_forwardable_copy()
            if copy_inst is None:
                break

            assert self._try_forward_copy(copy_inst)
            changed = True
            self._invalidate()

        if changed:
            self._invalidate()

    def _prepare(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.domtree = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.base_ptr = self.analyses_cache.request_analysis(BasePtrAnalysis)
        self.mem_alias = self.analyses_cache.request_analysis(MemoryAliasAnalysis)
        self.mem_ssa = self.analyses_cache.request_analysis(MemSSA)
        self.updater = InstUpdater(self.dfg)
        self.copy_forwarding = CopyForwardingPolicy(
            self.function, self.dfg, self.base_ptr, self.mem_alias
        )
        # Reuse the interprocedural readonly-param facts already used by the
        # invoke forwarding passes. They let this pass reason about internal
        # memory parameters whose concrete alloca is not visible pre-inlining.
        self.readonly_memory_args = self.analyses_cache.force_analysis(
            ReadonlyMemoryArgsGlobalAnalysis
        )
        # Cycles in the root graph are "all params" for mutability analysis,
        # but this transform must fail closed: an unresolvable source is not
        # proof that the source is a readonly internal param.
        self.param_roots = MemoryParamRootResolver(self.function, self.dfg, cycle_roots=frozenset())

    def _invalidate(self) -> None:
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(BasePtrAnalysis)
        self.analyses_cache.invalidate_analysis(MemSSA)

    def _find_forwardable_copy(self) -> IRInstruction | None:
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "mcopy" and self._copy_is_forwardable(inst):
                    return inst
        return None

    def _copy_is_forwardable(self, copy_inst: IRInstruction) -> bool:
        return self._candidate(copy_inst) is not None

    def _try_forward_copy(self, copy_inst: IRInstruction) -> bool:
        plan = self._candidate(copy_inst)
        if plan is None:
            return False

        self._apply_forward_plan(plan)
        self.updater.nop(copy_inst, annotation="[redundant memory copy forwarding]")
        return True

    def _candidate(self, copy_inst: IRInstruction) -> _ForwardPlan | None:
        copy_size = self.copy_forwarding.copy_size(copy_inst)
        if copy_size is None:
            return None
        if copy_size > _MAX_FORWARD_COPY_SIZE:
            return None

        src = self.copy_forwarding.copy_source(copy_inst)
        dst_ptr = self.base_ptr.ptr_from_op(copy_inst.operands[2])
        if dst_ptr is None or dst_ptr.offset is None:
            return None

        dst_root_inst = dst_ptr.base_alloca.inst
        if dst_root_inst is None or dst_root_inst.opcode != "alloca":
            return None

        dst_alloca = Allocation(dst_root_inst)
        if dst_alloca.is_dynamic or copy_size > dst_alloca.alloca_size:
            return None

        src_loc = self.base_ptr.get_read_location(copy_inst, addr_space.MEMORY)
        dst_loc = self.base_ptr.get_write_location(copy_inst, addr_space.MEMORY)
        if not dst_loc.is_fixed:
            return None
        src_is_readonly_param = False
        if src_loc.is_fixed:
            if src_loc.is_empty() or self.mem_alias.may_alias(src_loc, dst_loc):
                return None
            if src_loc.alloca is None:
                return None
            if src_loc.alloca is not None and src_loc.alloca.is_dynamic:
                return None
        elif self._source_is_readonly_param(src):
            src_is_readonly_param = True
        else:
            return None

        aliases = self.base_ptr.aliases_of_allocation(dst_alloca)
        if aliases is None:
            return None

        plan = self._build_forward_plan(copy_inst, src, dst_alloca, dst_loc, aliases)
        if plan is None:
            return None

        if self._has_location_clobber_between(copy_inst, plan.read_sites, dst_loc):
            return None

        if self._has_src_clobber_between(
            copy_inst, plan.read_sites, src_loc, src_is_readonly_param
        ):
            return None

        return plan

    def _build_forward_plan(
        self,
        copy_inst: IRInstruction,
        src: IROperand,
        dst_alloca: Allocation,
        dst_loc: MemoryLocation,
        aliases: set[IRVariable],
    ) -> _ForwardPlan | None:
        assert dst_loc.offset is not None and dst_loc.size is not None
        dst_start = dst_loc.offset
        dst_end = dst_start + dst_loc.size
        alias_rewrites = self._segment_aliases(dst_alloca, aliases, dst_start, dst_end)
        direct_read_rewrites = []
        read_sites: set[IRInstruction] = set()

        for alias in alias_rewrites:
            for use in self.dfg.get_uses(alias):
                for pos, op in enumerate(use.operands):
                    if op != alias:
                        continue
                    if use is copy_inst and pos == 2:
                        continue
                    if self._is_allowed_pointer_use(use, aliases):
                        continue
                    if self._is_allowed_memory_read_use(use, pos, copy_inst, dst_alloca, dst_loc):
                        read_sites.add(use)
                        continue
                    return None

        root = dst_alloca.inst.output
        for use in self.dfg.get_uses(root):
            for pos, op in enumerate(use.operands):
                if op != root:
                    continue
                if use is copy_inst and pos == 2:
                    continue
                if self._is_allowed_pointer_use(use, alias_rewrites.keys()):
                    continue
                if use.opcode in _POINTER_OPCODES:
                    if not use.has_outputs:
                        return None
                    if not self.base_ptr.pointer_uses_may_touch(
                        use.output, dst_loc, self.mem_alias
                    ):
                        continue
                    return None
                if self._is_allowed_direct_root_read(use, pos, copy_inst, dst_alloca, dst_loc):
                    read_loc = self.base_ptr.get_read_location(use, addr_space.MEMORY)
                    assert read_loc.offset is not None
                    direct_read_rewrites.append((use, pos, read_loc.offset - dst_start))
                    read_sites.add(use)
                    continue
                read_loc = self.base_ptr.get_read_location(use, addr_space.MEMORY)
                if self.mem_alias.may_alias(read_loc, dst_loc):
                    return None
                write_loc = self.base_ptr.get_write_location(use, addr_space.MEMORY)
                if use.get_write_effects() & Effects.MEMORY != EMPTY:
                    if self.mem_alias.may_alias(write_loc, dst_loc):
                        return None
                    continue
                if use.get_read_effects() & Effects.MEMORY == EMPTY:
                    return None

        if any(delta is None for delta in alias_rewrites.values()):
            return None

        if len(read_sites) == 0:
            return None

        return _ForwardPlan(
            copy_inst=copy_inst,
            src=src,
            alias_rewrites=alias_rewrites,
            direct_read_rewrites=tuple(direct_read_rewrites),
            read_sites=frozenset(read_sites),
        )

    def _segment_aliases(
        self, dst_alloca: Allocation, aliases: set[IRVariable], dst_start: int, dst_end: int
    ) -> dict[IRVariable, int | None]:
        root = dst_alloca.inst.output
        ret: dict[IRVariable, int | None] = {}

        for alias in aliases:
            if alias == root:
                continue
            ptr = self.base_ptr.ptr_from_op(alias)
            if ptr is None or ptr.base_alloca != dst_alloca or ptr.offset is None:
                continue
            if dst_start <= ptr.offset < dst_end:
                ret[alias] = ptr.offset - dst_start

        changed = True
        while changed:
            changed = False
            for alias in aliases:
                if alias in ret or alias == root:
                    continue
                inst = self.dfg.get_producing_instruction(alias)
                if inst is None or inst.opcode not in _POINTER_OPCODES:
                    continue
                if not any(isinstance(op, IRVariable) and op in ret for op in inst.operands):
                    continue
                ret[alias] = None
                changed = True

        return ret

    def _is_allowed_pointer_use(self, use: IRInstruction, aliases: Collection[IRVariable]) -> bool:
        if use.opcode not in _POINTER_OPCODES:
            return False
        if not use.has_outputs:
            return False
        return use.output in aliases

    def _is_allowed_memory_read_use(
        self,
        use: IRInstruction,
        operand_pos: int,
        copy_inst: IRInstruction,
        dst_alloca: Allocation,
        dst_loc: MemoryLocation,
    ) -> bool:
        if use.opcode == "return":
            return False

        if use.get_read_effects() & Effects.MEMORY == EMPTY:
            return False
        if not self._is_after(copy_inst, use):
            return False

        read_op = memory_read_ops(use).ofst
        if (
            read_op is None
            or operand_pos >= len(use.operands)
            or use.operands[operand_pos] != read_op
        ):
            return False

        read_loc = self.base_ptr.get_read_location(use, addr_space.MEMORY)
        if read_loc.alloca != dst_alloca:
            return False

        if use.get_write_effects() & Effects.MEMORY != EMPTY:
            write_loc = self.base_ptr.get_write_location(use, addr_space.MEMORY)
            if self.mem_alias.may_alias(write_loc, dst_loc):
                return False

        if read_loc.is_offset_fixed and read_loc.is_size_fixed:
            return dst_loc.completely_contains(read_loc)

        # Dynamic-offset reads are accepted only after they are derived from a
        # fixed alias inside this copied segment.  This matches Venom's
        # abstract-allocation contract before concretization.
        return True

    def _is_allowed_direct_root_read(
        self,
        use: IRInstruction,
        operand_pos: int,
        copy_inst: IRInstruction,
        dst_alloca: Allocation,
        dst_loc: MemoryLocation,
    ) -> bool:
        if not self._is_allowed_memory_read_use(use, operand_pos, copy_inst, dst_alloca, dst_loc):
            return False
        read_loc = self.base_ptr.get_read_location(use, addr_space.MEMORY)
        return read_loc.is_offset_fixed and read_loc.is_size_fixed

    def _has_src_clobber_between(
        self,
        copy_inst: IRInstruction,
        read_sites: frozenset[IRInstruction],
        src_loc: MemoryLocation,
        src_is_readonly_param: bool,
    ) -> bool:
        if src_is_readonly_param:
            return self._has_unresolved_param_clobber_between(copy_inst, read_sites)

        return self._has_location_clobber_between(copy_inst, read_sites, src_loc)

    def _has_location_clobber_between(
        self, copy_inst: IRInstruction, read_sites: frozenset[IRInstruction], loc: MemoryLocation
    ) -> bool:
        return self.mem_ssa.is_clobbered_between(copy_inst, read_sites, loc, ignore=(copy_inst,))

    def _has_unresolved_param_clobber_between(
        self, copy_inst: IRInstruction, read_sites: frozenset[IRInstruction]
    ) -> bool:
        # An unresolved readonly param is clobbered only by a write to an
        # unknown base (alloca is None). Filtering on `alloca is None` is
        # transform policy, so we compose it here over MemSSA's reachable
        # alias walk for the conservative UNDEFINED location.
        accesses = self.mem_ssa.clobbering_accesses_between(
            copy_inst, read_sites, MemoryLocation.UNDEFINED, ignore=(copy_inst,)
        )
        for access in accesses:
            write_loc = access.loc
            if write_loc.alloca is None and not write_loc.is_empty():
                return True

        return False

    def _apply_forward_plan(self, plan: _ForwardPlan) -> None:
        for alias, delta in plan.alias_rewrites.items():
            if delta is None:
                continue
            inst = self.dfg.get_producing_instruction(alias)
            if inst is None:
                continue
            if delta == 0:
                self.updater.update(
                    inst, "assign", [plan.src], annotation="[redundant memory copy forwarding]"
                )
            else:
                self.updater.update(
                    inst,
                    "add",
                    [IRLiteral(delta), plan.src],
                    annotation="[redundant memory copy forwarding]",
                )

        for use, pos, delta in plan.direct_read_rewrites:
            new_op = self._source_at(plan.src, delta, use)
            new_operands = list(use.operands)
            new_operands[pos] = new_op
            self.updater.update(
                use, use.opcode, new_operands, annotation="[redundant memory copy forwarding]"
            )

    def _source_at(self, src: IROperand, delta: int, inst: IRInstruction) -> IROperand:
        if delta == 0:
            return src
        new_var = self.updater.add_before(inst, "add", [IRLiteral(delta), src])
        assert new_var is not None
        return new_var

    def _source_is_readonly_param(self, src: IROperand) -> bool:
        roots = self.param_roots.root_param_indices(src)
        if len(roots) == 0:
            return False

        readonly_idxs = self.readonly_memory_args.get_readonly_invoke_arg_idxs(self.function)
        return roots.issubset(readonly_idxs)

    def _is_after(self, copy_inst: IRInstruction, use_inst: IRInstruction) -> bool:
        copy_bb = copy_inst.parent
        use_bb = use_inst.parent

        if use_bb is copy_bb:
            bb_insts = copy_bb.instructions
            return bb_insts.index(use_inst) > bb_insts.index(copy_inst)

        return self.domtree.dominates(copy_bb, use_bb)
