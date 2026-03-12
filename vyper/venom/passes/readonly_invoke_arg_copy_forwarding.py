from __future__ import annotations

from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.passes.invoke_copy_forwarding_common import InvokeCopyForwardingBase


class ReadonlyInvokeArgCopyForwardingPass(InvokeCopyForwardingBase):
    """
    Forward staged memory args into readonly invoke parameters:

      %tmp = alloca/calloca ...
      mcopy %tmp, %src, ...
      invoke @callee, ..., %tmp, ...

    Only readonly callee memory params are rewritten.
    """

    def run_pass(self):
        self._prepare()
        changed = False

        # Run to a local fixpoint so chained staging copies are fully
        # collapsed in a single pass invocation.
        while True:
            iter_changed = False
            for bb in self.function.get_basic_blocks():
                for inst in list(bb.instructions):
                    if inst.opcode != "mcopy":
                        continue
                    iter_changed |= self._try_forward_readonly_copy(inst)

            if not iter_changed:
                break
            changed = True

        self._finish(changed)

    def _try_forward_readonly_copy(self, copy_inst: IRInstruction) -> bool:
        dst = copy_inst.operands[2]
        if not isinstance(dst, IRVariable):
            return False

        root = self._assign_root_var(dst)
        root_inst = self.dfg.get_producing_instruction(root)
        if root_inst is None or root_inst.opcode not in ("alloca", "calloca"):
            return False

        aliases = self._collect_assign_aliases(root)
        rewrite_sites: set[tuple[IRInstruction, int]] = set()

        for _, use, pos in self._iter_alias_use_positions(aliases):
            if self._is_assign_output_use(use, pos):
                continue
            if use.opcode == "mcopy" and pos == 2:
                if use is not copy_inst:
                    return False
                continue
            if use.opcode == "invoke" and self._is_readonly_invoke_operand(use, pos):
                rewrite_sites.add((use, pos))
                continue
            return False

        if len(rewrite_sites) == 0:
            return False

        # Keep this local and conservative: only forward when all uses are
        # in the same block and dominated by the source copy.
        bb_insts = copy_inst.parent.instructions
        copy_idx = bb_insts.index(copy_inst)
        for invoke_inst, _ in rewrite_sites:
            if invoke_inst.parent is not copy_inst.parent:
                return False
            if bb_insts.index(invoke_inst) < copy_idx:
                return False

        if self._has_src_clobber_between(copy_inst, rewrite_sites):
            return False

        src = self._assign_root(copy_inst.operands[1])
        if isinstance(src, IRVariable) and src in aliases:
            return False
        if isinstance(src, IRVariable) and self._has_mutable_same_source_sibling_arg(
            rewrite_sites, src
        ):
            return False

        for invoke_inst, pos in rewrite_sites:
            if invoke_inst.operands[pos] == src:
                continue
            new_operands = list(invoke_inst.operands)
            new_operands[pos] = src
            self.updater.update(invoke_inst, invoke_inst.opcode, new_operands)

        # Even when operands already point to src, this copy is redundant:
        # all remaining uses are readonly invokes validated above.
        self.updater.nop(copy_inst)
        return True

    def _has_mutable_same_source_sibling_arg(
        self, rewrite_sites: set[tuple[IRInstruction, int]], src_root: IRVariable
    ) -> bool:
        """
        Reject forwarding when it would create aliasing between a rewritten
        readonly arg and a sibling mutable arg in the same invoke.
        """
        for invoke_inst, rewritten_pos in rewrite_sites:
            for pos, op in enumerate(invoke_inst.operands):
                if pos == 0 or pos == rewritten_pos:
                    continue
                if self._is_readonly_invoke_operand(invoke_inst, pos):
                    continue
                root = self._assign_root(op)
                if root == src_root:
                    return True
        return False
