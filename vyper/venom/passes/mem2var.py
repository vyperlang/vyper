from vyper.utils import all2
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


class Mem2Var(IRPass):
    """
    This pass promoted memory operations to variable operations, when possible.
    It does yet do any memory aliasing analysis, so it is conservative.
    """

    function: IRFunction

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.var_name_count = 0
        for var, inst in dfg.outputs.items():
            if inst.opcode == "alloca":
                self._process_alloca_var(dfg, inst, var)
            elif inst.opcode == "palloca":
                self._process_palloca_var(dfg, inst, var)

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _mk_varname(self, varname: str, alloca_id: int):
        varname = varname.removeprefix("%")
        varname = f"alloca_{alloca_id}_{varname}_{self.var_name_count}"
        self.var_name_count += 1
        return varname

    def _process_alloca_var(self, dfg: DFGAnalysis, alloca_inst, var: IRVariable):
        """
        Process alloca allocated variable. If it is only used by
        mstore/mload/return instructions, it is promoted to a stack variable.
        Otherwise, it is left as is.
        """
        uses = dfg.get_uses(var)
        if not all2(inst.opcode in ["mstore", "mload", "return"] for inst in uses):
            return

        alloca_id = alloca_inst.operands[2]
        var_name = self._mk_varname(var.value, alloca_id.value)
        var = IRVariable(var_name)
        for inst in uses:
            if inst.opcode == "mstore":
                inst.opcode = "store"
                inst.output = var
                inst.operands = [inst.operands[0]]
            elif inst.opcode == "mload":
                inst.opcode = "store"
                inst.operands = [var]
            elif inst.opcode == "return":
                bb = inst.parent
                idx = len(bb.instructions) - 1
                assert inst == bb.instructions[idx]  # sanity
                new_inst = IRInstruction("mstore", [var, inst.operands[1]])
                bb.insert_instruction(new_inst, idx)

    def _process_palloca_var(self, dfg: DFGAnalysis, palloca_inst: IRInstruction, var: IRVariable):
        """
        Process alloca allocated variable. If it is only used by mstore/mload
        instructions, it is promoted to a stack variable. Otherwise, it is left as is.
        """
        uses = dfg.get_uses(var)
        if not all2(inst.opcode in ["mstore", "mload"] for inst in uses):
            return

        ofst, _size, alloca_id = palloca_inst.operands
        var_name = self._mk_varname(var.value, alloca_id.value)
        var = IRVariable(var_name)

        # some value given to us by the calling convention
        palloca_inst.opcode = "mload"
        palloca_inst.operands = [ofst]
        palloca_inst.output = var

        for inst in uses:
            if inst.opcode == "mstore":
                inst.opcode = "store"
                inst.output = var
                inst.operands = [inst.operands[0]]
            elif inst.opcode == "mload":
                inst.opcode = "store"
                inst.operands = [var]
