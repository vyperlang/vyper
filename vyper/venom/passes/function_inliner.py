from vyper.utils import OrderedSet
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction,IRBasicBlock,IRVariable
from vyper.venom.passes.base_pass import IRPass

from collections import deque

class FunctionInlinerPass(IRPass):
    """
    This pass removes instructions that produce output that is never used.
    """
    def run_pass(self):
        self._alloca_map = self._build_alloca_map()

        self.worklist = deque(self.function.get_basic_blocks())
        while len(self.worklist) > 0:
            bb = self.worklist.popleft()
            for idx, inst in enumerate(bb.instructions):
                if inst.opcode == "invoke":
                    self._handle_invoke(inst, idx)
                    break

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)

    def _build_alloca_map(self):
        ret = {}
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode.startswith("alloca"):
                    ret[tuple(inst.operands)] = inst
        return ret

    def _handle_invoke(self, invoke_inst, invoke_idx):
        fn = self.function
        ctx = fn.ctx

        target_label = invoke_inst.operands[0]
        target_function = ctx.functions[target_label]

        bbs = list(target_function.get_basic_blocks())

        var_map = {}

        next_bb = IRBasicBlock(ctx.get_next_label(), fn)

        # make copies of every bb and inline them into the code
        for bb in bbs:
            new_label = ctx.get_next_label()
            new_bb = IRBasicBlock(new_label, fn)
            new_bb.instructions = bb.instructions.copy()
            for i, inst in enumerate(new_bb.instructions):
                new_var = fn.get_next_variable()
                var_map[inst.output] = new_var

                inst = inst.copy()
                inst.parent = new_bb

                for j, op in enumerate(inst.operands):
                    if isinstance(op, IRVariable):
                        inst.operands[j] = var_map[inst.operands[j]]

                if inst.opcode.startswith("palloca"):
                    alloca_id = tuple(inst.operands)
                    inst.opcode = "store"
                    var_map[inst.output] = self._alloca_map[alloca_id].output
                if inst.opcode == "ret":
                    inst.opcode = "jmp"
                    inst.operands = [next_bb.label]
                    inst.output = None


                # note: don't transform the operands for param
                if inst.opcode == "param":
                    inst.opcode = "store"
                    inst.operands = [invoke_inst.operands[-i-1]]

            fn.append_basic_block(new_bb)
            self.worklist.append(new_bb)

        bb = invoke_inst.parent
        assert invoke_idx < len(bb.instructions), (invoke_idx, bb)
        next_bb.instructions = bb.instructions[invoke_idx+1:]
        for inst in next_bb.instructions:
            inst.parent = next_bb
        fn.append_basic_block(next_bb)
        self.worklist.append(next_bb)

        del bb.instructions[invoke_idx+1:]
        invoke_inst.opcode = "jmp"
        invoke_inst.operands = [next_bb.label]
        invoke_inst.output = None
