from collections import deque

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, IRAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable


class LivenessAnalysis(IRAnalysis):
    """
    Compute liveness information for each instruction in the function.
    """

    cfg: CFGAnalysis

    _out_vars: dict[IRBasicBlock, OrderedSet[IRVariable]]
    inst_to_liveness: dict[IRInstruction, OrderedSet[IRVariable]]

    def analyze(self):
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)

        self._out_vars = {}
        self.inst_to_liveness = {}
        for bb in self.function.get_basic_blocks():
            self._out_vars[bb] = OrderedSet()
            for inst in bb.instructions:
                self.inst_to_liveness[inst] = OrderedSet()

        worklist = deque(self.cfg.dfs_post_walk)

        while len(worklist) > 0:
            changed = False

            bb = worklist.popleft()
            changed |= self._calculate_out_vars(bb)
            changed |= self._calculate_liveness(bb)
            # recompute liveness for basic blocks pointing into
            # this basic block
            if changed:
                worklist.extend(self.cfg.cfg_in(bb))

    def _calculate_liveness(self, bb: IRBasicBlock) -> bool:
        """
        Compute liveness of each instruction in the basic block.
        Returns True if liveness changed
        """
        orig_liveness = self.inst_to_liveness[bb.instructions[0]].copy()
        liveness = self._out_vars[bb].copy()
        for instruction in reversed(bb.instructions):
            ins = instruction.get_input_variables()
            outs = instruction.get_outputs()

            if ins or outs:
                # perf: only copy if changed
                liveness = liveness.copy()
                liveness.update(ins)
                liveness.dropmany(outs)

            self.inst_to_liveness[instruction] = liveness

        return orig_liveness != self.inst_to_liveness[bb.instructions[0]]

    def _calculate_out_vars(self, bb: IRBasicBlock) -> bool:
        """
        Compute out_vars of basic block.
        Returns True if out_vars changed
        """
        out_vars = self._out_vars[bb].copy()
        self._out_vars[bb] = OrderedSet()
        for out_bb in self.cfg.cfg_out(bb):
            target_vars = self.input_vars_from(bb, out_bb)
            self._out_vars[bb].update(target_vars)
        return out_vars != self._out_vars[bb]

    def liveness_in_vars(self, bb):
        for inst in bb.instructions:
            if inst.opcode != "phi":
                return self.inst_to_liveness[inst]
        return OrderedSet()

    def out_vars(self, bb: IRBasicBlock) -> OrderedSet[IRVariable]:
        """
        Return variables that are live at exit of basic block
        """
        return self._out_vars[bb]

    def live_vars_at(self, inst: IRInstruction) -> OrderedSet[IRVariable]:
        """
        Get the variables that are live at (right before) a given instruction
        """
        return self.inst_to_liveness[inst]

    # calculate the input variables into self from source
    def input_vars_from(self, source: IRBasicBlock, target: IRBasicBlock) -> OrderedSet[IRVariable]:
        liveness = self.inst_to_liveness[target.instructions[0]].copy()

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

    def invalidate(self):
        # delete properties so they can't accidentally be used
        del self._out_vars
        del self.inst_to_liveness
