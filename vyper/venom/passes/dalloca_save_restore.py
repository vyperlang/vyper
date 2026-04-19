from vyper.utils import MemoryPositions
from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes.base_pass import IRPass


class DallocaSaveRestore(IRPass):
    """
    For every function that contains a `dalloca`, save the free-memory
    pointer on function entry and restore it before every `ret`. This
    reclaims dynamically allocated memory across function boundaries.
    """

    required_predecessors = ("DallocaPromotion",)

    def run_pass(self):
        fn = self.function
        if not self._function_has_dalloca(fn):
            return

        ret_blocks = [
            bb
            for bb in fn.get_basic_blocks()
            if len(bb.instructions) > 0 and bb.instructions[-1].opcode == "ret"
        ]
        if len(ret_blocks) == 0:
            return

        saved = fn.get_next_variable()
        entry = fn.entry
        load_inst = IRInstruction("mload", [IRLiteral(MemoryPositions.FREE_MEM_PTR)], [saved])
        insert_idx = 0
        for i, inst in enumerate(entry.instructions):
            if inst.opcode in ("phi", "param"):
                insert_idx = i + 1
                continue
            break
        entry.insert_instruction(load_inst, index=insert_idx)

        for bb in ret_blocks:
            term = bb.instructions[-1]
            store_inst = IRInstruction("mstore", [saved, IRLiteral(MemoryPositions.FREE_MEM_PTR)])
            idx = bb.instructions.index(term)
            bb.insert_instruction(store_inst, index=idx)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _function_has_dalloca(self, fn) -> bool:
        return any(
            inst.opcode == "dalloca" for bb in fn.get_basic_blocks() for inst in bb.instructions
        )
