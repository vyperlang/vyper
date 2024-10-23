from vyper.exceptions import UnreachableStackException
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.mem_allocator import MemoryAllocator
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.venom_to_assembly import VenomCompiler


class Stack2Mem(IRPass):
    mem_allocator: MemoryAllocator

    def run_pass(self):
        fn = self.function
        self.mem_allocator = self.function.ctx.mem_allocator
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.analyses_cache.request_analysis(LivenessAnalysis)

        while True:
            compiler = VenomCompiler([fn.ctx])
            try:
                compiler.generate_evm()
                break
            except Exception as e:
                if isinstance(e, UnreachableStackException):
                    self._demote_variable(dfg, e.op)
                    self.analyses_cache.force_analysis(LivenessAnalysis)
                else:
                    break

        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def _demote_variable(self, dfg: DFGAnalysis, var: IRVariable):
        """
        Demote a stack variable to memory operations.
        """
        uses = dfg.get_uses(var)
        def_inst = dfg.get_producing_instruction(var)

        # Allocate memory for this variable
        mem_addr = self.mem_allocator.allocate(32)

        if def_inst is not None:
            self._insert_mstore_after(def_inst, mem_addr)

        for inst in uses:
            self._insert_mload_before(inst, mem_addr, var)

    def _insert_mstore_after(self, inst: IRInstruction, mem_addr: int):
        bb = inst.parent
        idx = bb.instructions.index(inst)
        assert inst.output is not None
        # mem_var = IRVariable(f"mem_{mem_addr}")
        # bb.insert_instruction(
        #     IRInstruction("alloca", [IRLiteral(mem_addr), 32], mem_var), idx + 1
        # )
        new_var = self.function.get_next_variable()
        bb.insert_instruction(IRInstruction("mstore", [new_var, IRLiteral(mem_addr)]), idx + 1)
        inst.output = new_var

    def _insert_mload_before(self, inst: IRInstruction, mem_addr: int, var: IRVariable):
        bb = inst.parent
        idx = bb.instructions.index(inst)
        new_var = self.function.get_next_variable()
        load_inst = IRInstruction("mload", [IRLiteral(mem_addr)])
        load_inst.output = new_var
        bb.insert_instruction(load_inst, idx)
        inst.replace_operands({var: new_var})
