from collections import defaultdict, deque

from vyper.compiler.settings import OptimizationLevel
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import CFG_ALTERING_INSTRUCTIONS, IRBasicBlock, IRLabel, IRVariable
from vyper.venom.passes.base_pass import IRPass


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
                if inst.opcode == "invoke" and self._handle_invoke(inst, idx):
                    break

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _build_alloca_map(self):
        ret = {}
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode.startswith("alloca"):
                    ret[tuple(inst.operands)] = inst
        return ret

    @property
    def _threshold(self):
        optimize = self.analyses_cache.optimize
        if optimize == OptimizationLevel.GAS:
            return 100
        if optimize == OptimizationLevel.CODESIZE:
            return 15

    def _handle_invoke(self, invoke_inst, invoke_idx):
        fn = self.function
        ctx = fn.ctx

        target_label = invoke_inst.operands[0]
        target_function = ctx.functions[target_label]

        bbs = list(target_function.get_basic_blocks())

        # TODO: the number of times a function is called globally is also
        # important
        # TODO: check the threshold after the function is optimized
        if sum(len(bb.instructions) for bb in bbs) > self._threshold:
            return False

        var_map = {}

        next_bb = IRBasicBlock(ctx.get_next_label(), fn)

        label_map = defaultdict(ctx.get_next_label)

        # make copies of every bb and inline them into the code
        for bb in bbs:
            new_label = label_map[bb.label]
            new_bb = IRBasicBlock(new_label, fn)

            if bb is target_function.entry:
                target_bb = new_bb

            for i, inst in enumerate(bb.instructions):
                inst = inst.copy()
                inst.parent = new_bb
                new_bb.instructions.append(inst)

                for j, op in enumerate(inst.operands):
                    if isinstance(op, IRVariable):
                        inst.operands[j] = var_map[op]
                    if inst.opcode in CFG_ALTERING_INSTRUCTIONS and isinstance(op, IRLabel):
                        inst.operands[j] = label_map[op]

                if inst.opcode == "ret":
                    inst.opcode = "jmp"
                    inst.operands = [next_bb.label]
                    inst.output = None
                if inst.opcode.startswith("palloca"):
                    alloca_id = tuple(inst.operands)
                    inst.opcode = "store"
                    inst.operands = [self._alloca_map[alloca_id].output]
                if inst.opcode == "param":
                    inst.opcode = "store"
                    op = invoke_inst.operands[-i - 1]
                    inst.operands = [invoke_inst.operands[-i - 1]]

                new_var = fn.get_next_variable()
                var_map[inst.output] = new_var
                inst.output = new_var

            fn.append_basic_block(new_bb)
            self.worklist.append(new_bb)

        bb = invoke_inst.parent
        assert invoke_idx < len(bb.instructions), (invoke_idx, bb)
        next_bb.instructions = bb.instructions[invoke_idx + 1 :]
        for inst in next_bb.instructions:
            inst.parent = next_bb
        fn.append_basic_block(next_bb)
        self.worklist.append(next_bb)

        bb.instructions = bb.instructions[: invoke_idx + 1]
        assert len(bb.instructions) - 1 == invoke_idx
        invoke_inst.opcode = "jmp"
        invoke_inst.operands = [target_bb.label]
        invoke_inst.output = None
        return True
