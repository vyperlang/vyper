from vyper.utils import all2
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ENABLE_NEW_CALL_CONV
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class Mem2Var(IRPass):
    """
    This pass promoted memory operations to variable operations, when possible.
    It does yet do any memory aliasing analysis, so it is conservative.
    """

    function: IRFunction

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(dfg)

        self.var_name_count = 0
        for var, inst in dfg.outputs.copy().items():
            if inst.opcode == "alloca":
                self._process_alloca_var(dfg, inst, var)
            elif inst.opcode == "palloca":
                self._process_palloca_var(dfg, inst, var)

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
        for inst in uses.copy():
            if inst.opcode == "mstore":
                self.updater.mk_assign(inst, inst.operands[0], new_output=var)
            elif inst.opcode == "mload":
                self.updater.mk_assign(inst, var)
            elif inst.opcode == "return":
                self.updater.add_before(inst, "mstore", [var, inst.operands[1]])

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
        fn = self.function
        if ENABLE_NEW_CALL_CONV:
            # it comes as a stack parameter. this (reifying with param based
            # on alloca_id) is a bit kludgey, but we will live.
            param = fn.get_param_by_id(alloca_id.value)
            if param is None:
                self.updater.update(palloca_inst, "mload", [ofst], new_output=var)
            else:
                self.updater.update(palloca_inst, "assign", [param.func_var], new_output=var)
        else:
            # otherwise, it comes from memory, convert to an mload.
            self.updater.update(palloca_inst, "mload", [ofst], new_output=var)

        for inst in uses.copy():
            if inst.opcode == "mstore":
                self.updater.mk_assign(inst, inst.operands[0], new_output=var)
            elif inst.opcode == "mload":
                self.updater.mk_assign(inst, var)
