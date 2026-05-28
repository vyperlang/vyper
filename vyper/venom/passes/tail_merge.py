from vyper.exceptions import CompilerPanic
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.base_pass import IRPass


class TailMergePass(IRPass):
    """
    Merge structurally equivalent terminal basic blocks.

    This is a conservative MVP:
    - only reachable, non-entry, halting blocks are considered
    - blocks with phi nodes are ignored
    - blocks with live-in variables are ignored
    """

    cfg: CFGAnalysis
    required_immediate_successors = ("SimplifyCFGPass",)

    def run_pass(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        label_map = self._merge_equivalent_tails()
        if len(label_map) > 0:
            self._replace_all_labels(label_map)
            self.analyses_cache.invalidate_analysis(CFGAnalysis)
            self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _merge_equivalent_tails(self) -> dict[IRLabel, IRLabel]:
        groups: dict[tuple, IRBasicBlock] = {}
        to_remove: list[IRBasicBlock] = []
        label_map: dict[IRLabel, IRLabel] = {}

        for bb in self.function.get_basic_blocks():
            if bb == self.function.entry:
                continue
            if not self.cfg.is_reachable(bb):
                continue

            signature = self._block_signature(bb)
            if signature is None:
                continue

            keeper = groups.get(signature)
            if keeper is None:
                groups[signature] = bb
                continue

            label_map[bb.label] = keeper.label
            to_remove.append(bb)

        for bb in to_remove:
            self.function.remove_basic_block(bb)

        return label_map

    def _block_signature(self, bb: IRBasicBlock) -> tuple | None:
        if not bb.is_halting:
            return None

        # reject blocks with phis or non-local variable inputs
        defined: set[IRVariable] = set()
        for inst in bb.instructions:
            if inst.opcode == "phi":
                return None
            for op in inst.get_input_variables():
                if op not in defined:
                    return None
            defined.update(inst.get_outputs())

        var_map: dict[IRVariable, str] = {}

        def _canon_var(var: IRVariable) -> str:
            if var not in var_map:
                var_map[var] = f"v{len(var_map)}"
            return var_map[var]

        def _canon_operand(op: IROperand):
            if isinstance(op, IRVariable):
                return ("var", _canon_var(op))
            if isinstance(op, IRLiteral):
                return ("lit", op.value)
            if isinstance(op, IRLabel):
                return ("label", op.value)
            raise CompilerPanic(f"unexpected operand type in tail merge: {type(op)}")

        signature = []
        for inst in bb.instructions:
            outputs = tuple(_canon_var(out) for out in inst.get_outputs())
            operands = tuple(_canon_operand(op) for op in inst.operands)
            signature.append((inst.opcode, outputs, operands))

        return tuple(signature)
