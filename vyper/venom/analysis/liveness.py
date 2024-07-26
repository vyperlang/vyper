from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRVariable


class LivenessAnalysis(IRAnalysis):
    """
    Compute liveness information for each instruction in the function.
    """

    def analyze(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        self._reset_liveness()
        while True:
            changed = False
            for bb in self.function.get_basic_blocks():
                changed |= self._calculate_out_vars(bb)
                changed |= self._calculate_liveness(bb)

            if not changed:
                break

    def _reset_liveness(self) -> None:
        for bb in self.function.get_basic_blocks():
            bb.out_vars = OrderedSet()
            for inst in bb.instructions:
                inst.liveness = OrderedSet()

    def _calculate_liveness(self, bb: IRBasicBlock) -> bool:
        """
        Compute liveness of each instruction in the basic block.
        Returns True if liveness changed
        """
        orig_liveness = bb.instructions[0].liveness.copy()
        liveness = bb.out_vars.copy()
        for instruction in reversed(bb.instructions):
            ins = instruction.get_input_variables()
            outs = instruction.get_outputs()

            if ins or outs:
                # perf: only copy if changed
                liveness = liveness.copy()
                liveness.update(ins)
                liveness.dropmany(outs)

            instruction.liveness = liveness

        return orig_liveness != bb.instructions[0].liveness

    def _calculate_out_vars(self, bb: IRBasicBlock) -> bool:
        """
        Compute out_vars of basic block.
        Returns True if out_vars changed
        """
        out_vars = bb.out_vars
        bb.out_vars = OrderedSet()
        for out_bb in bb.cfg_out:
            target_vars = self.input_vars_from(bb, out_bb)
            bb.out_vars = bb.out_vars.union(target_vars)
        return out_vars != bb.out_vars

    # calculate the input variables into self from source
    def input_vars_from(self, source: IRBasicBlock, target: IRBasicBlock) -> OrderedSet[IRVariable]:
        liveness = target.instructions[0].liveness.copy()
        assert isinstance(liveness, OrderedSet)

        for inst in target.instructions:
            if inst.opcode == "phi":
                # we arbitrarily choose one of the arguments to be in the
                # live variables set (dependent on how we traversed into this
                # basic block). the argument will be replaced by the destination
                # operand during instruction selection.
                # for instance, `%56 = phi %label1 %12 %label2 %14`
                # will arbitrarily choose either %12 or %14 to be in the liveness
                # set, and then during instruction selection, after this instruction,
                # %12 will be replaced by %56 in the liveness set

                # bad path into this phi node
                if source.label not in inst.operands:
                    raise CompilerPanic(f"unreachable: {inst} from {source.label}")

                for label, var in inst.phi_operands:
                    if label == source.label:
                        liveness.add(var)
                    else:
                        if var in liveness:
                            liveness.remove(var)

        return liveness
