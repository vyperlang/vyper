from vyper.utils import wrap256
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.passes.algebraic_optimization import VarInfo, _lookup, _push_size, transfer_add, transfer_assign, transfer_sub
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class AffineFoldingPass(IRPass):
    """
    Lattice-driven affine chain folding.

    Collapses chains of add/sub into single operations using a forward
    dataflow analysis (VarInfo lattice). For example:
        add(add(x, 3), 5)  =>  add(x, 8)
    """

    dfg: DFGAnalysis
    updater: InstUpdater
    var_info: dict[IRVariable, VarInfo]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self.var_info = self._compute_var_info()
        self._rewrite_all()
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _compute_var_info(self) -> dict[IRVariable, VarInfo]:
        info: dict[IRVariable, VarInfo] = {}
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.num_outputs != 1:
                    continue
                if inst.opcode == "add":
                    lhs = _lookup(inst.operands[1], info)
                    rhs = _lookup(inst.operands[0], info)
                    info[inst.output] = transfer_add(lhs, rhs, inst.output)
                elif inst.opcode == "sub":
                    minuend = _lookup(inst.operands[1], info)
                    subtrahend = _lookup(inst.operands[0], info)
                    info[inst.output] = transfer_sub(minuend, subtrahend, inst.output)
                elif inst.opcode == "assign":
                    info[inst.output] = transfer_assign(_lookup(inst.operands[0], info))
                else:
                    info[inst.output] = VarInfo.of(inst.output)
        return info

    def _rewrite_all(self):
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.num_outputs != 1:
                    continue
                if inst.is_volatile or inst.opcode == "assign" or inst.is_pseudo:
                    continue
                self._rewrite_affine(inst)

    def _rewrite_affine(self, inst: IRInstruction) -> bool:
        """Lattice-driven affine chain folding."""
        if inst.opcode not in ("add", "sub"):
            return False
        vi = self.var_info.get(inst.output)
        if vi is None or vi.base is None:
            return False

        base = vi.base
        offset = vi.offset
        if base == inst.output:
            return False
        if isinstance(base, IRLabel):
            return False

        # Find the immediate variable operand and current literal
        if inst.opcode == "add":
            val_op, lit_op = self._extract_value_and_literal_operands(inst)
            if val_op is None or lit_op is None:
                return False
            imm_base = val_op
            curr_lit = lit_op.value
        else:  # sub
            op0, op1 = inst.operands
            if not isinstance(op0, IRLiteral) or isinstance(op1, IRLiteral):
                return False
            imm_base = op1
            curr_lit = op0.value

        # Only rewrite if chain folding found a deeper base
        if base == imm_base:
            return False

        # Walk from imm_base toward lattice base, stopping at the first
        # multi-use intermediate. This preserves shared base pointers
        # for CSE/DFT (e.g. alloca+64 used by multiple mcopy destinations).
        eff_base = self._effective_affine_base(imm_base, base)
        if eff_base == imm_base:
            return False

        # compute offset relative to effective base
        if eff_base == base:
            eff_offset = offset
        else:
            if not isinstance(eff_base, IRVariable):
                return False
            vi_eff = self.var_info.get(eff_base)
            if vi_eff is None or vi_eff.base != base:
                return False
            eff_offset = wrap256(offset - vi_eff.offset)

        if eff_offset == 0:
            self.updater.mk_assign(inst, eff_base)
            return True

        # Don't rewrite if it would increase literal byte width
        if _push_size(eff_offset) > _push_size(curr_lit):
            return False

        self.updater.update(inst, "add", [eff_base, IRLiteral(eff_offset)])
        return True

    def _effective_affine_base(self, imm_base: IROperand, lattice_base: IROperand) -> IROperand:
        """Walk producers from imm_base toward lattice_base, return the
        deepest reachable base without crossing multi-use intermediates."""
        current = imm_base
        while current != lattice_base:
            if not isinstance(current, IRVariable):
                return current
            if not self.dfg.is_single_use(current):
                return current
            prod = self.dfg.get_producing_instruction(current)
            if prod is None:
                return current
            if prod.opcode == "assign":
                current = prod.operands[0]
            elif prod.opcode == "add":
                val_op, lit_op = self._extract_value_and_literal_operands(prod)
                if val_op is None or lit_op is None:
                    return current
                current = val_op
            else:
                return current
        return lattice_base

    def _extract_value_and_literal_operands(
        self, inst: IRInstruction
    ) -> tuple[IROperand | None, IRLiteral | None]:
        value_op = None
        literal_op = None
        for op in inst.operands:
            if isinstance(op, IRLiteral):
                if literal_op is not None:
                    return None, None
                literal_op = op
            else:
                value_op = op
        assert isinstance(literal_op, IRLiteral) or literal_op is None  # help mypy
        return value_op, literal_op
