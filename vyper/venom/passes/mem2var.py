from vyper.utils import all2
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRAbstractMemLoc, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.ir_node_to_venom import ENABLE_NEW_CALL_CONV
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class Mem2Var(IRPass):
    """
    This pass promoted memory operations to variable operations, when possible.
    It does yet do any memory aliasing analysis, so it is conservative.
    """

    function: IRFunction

    def run_pass(self, mem_alloc):
        self.mem_alloc = mem_alloc
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(dfg)

        self.var_name_count = 0
        for var, inst in dfg.outputs.copy().items():
            if inst.opcode == "alloca":
                self._process_alloca_var(dfg, inst, var)
            elif inst.opcode == "palloca":
                self._process_palloca_var(dfg, inst, var)
            elif inst.opcode == "calloca":
                self._process_calloca(inst)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _mk_varname(self, varname: str, alloca_id: int):
        varname = varname.removeprefix("%")
        varname = f"alloca_{alloca_id}_{varname}_{self.var_name_count}"
        self.var_name_count += 1
        return varname

    def _process_alloca_var(self, dfg: DFGAnalysis, alloca_inst: IRInstruction, var: IRVariable):
        """
        Process alloca allocated variable. If it is only used by
        mstore/mload/return instructions, it is promoted to a stack variable.
        Otherwise, it is left as is.
        """

        assert len(alloca_inst.operands) == 2, (alloca_inst, alloca_inst.parent)

        mem_loc, alloca_id = alloca_inst.operands
        var_name = self._mk_varname(var.value, alloca_id.value)
        var = IRVariable(var_name)
        assert alloca_inst.output is not None
        uses = dfg.get_uses(alloca_inst.output)

        self.updater.mk_assign(alloca_inst, mem_loc)

        if any(inst.opcode == "add" for inst in uses):
            for inst in uses.copy():
                if inst.opcode == "add":
                    other = [op for op in inst.operands if op != alloca_inst.output]
                    assert len(other) == 1
                    self.updater.update(inst, "gep", [mem_loc, other[0]])
            return
        if not all2(inst.opcode in ["mstore", "mload", "return"] for inst in uses):
            return

        assert isinstance(mem_loc, IRAbstractMemLoc)
        size = mem_loc.size

        for inst in uses.copy():
            if inst.opcode == "mstore":
                if size <= 32:
                    self.updater.mk_assign(inst, inst.operands[0], new_output=var)
                else:
                    self.updater.update_operands(inst, {alloca_inst.output: mem_loc})
            elif inst.opcode == "mload":
                if size <= 32:
                    self.updater.mk_assign(inst, var)
                else:
                    self.updater.update_operands(inst, {alloca_inst.output: mem_loc})
            elif inst.opcode == "return":
                if size <= 32:
                    self.updater.add_before(inst, "mstore", [var, mem_loc])
                inst.operands[1] = mem_loc

    def _process_palloca_var(self, dfg: DFGAnalysis, palloca_inst: IRInstruction, var: IRVariable):
        """
        Process alloca allocated variable. If it is only used by mstore/mload
        instructions, it is promoted to a stack variable. Otherwise, it is left as is.
        """
        mem_loc, alloca_id = palloca_inst.operands
        assert palloca_inst.output is not None
        uses = dfg.get_uses(palloca_inst.output)

        self.updater.mk_assign(palloca_inst, mem_loc)
        if any(inst.opcode == "add" for inst in uses):
            for inst in uses.copy():
                if inst.opcode == "add":
                    other = [op for op in inst.operands if op != palloca_inst.output]
                    assert len(other) == 1
                    self.updater.update(inst, "gep", [mem_loc, other[0]])
            return

        if not all2(inst.opcode in ["mstore", "mload"] for inst in uses):
            return

        # some value given to us by the calling convention
        fn = self.function
        if ENABLE_NEW_CALL_CONV:
            # it comes as a stack parameter. this (reifying with param based
            # on alloca_id) is a bit kludgey, but we will live.
            param = fn.get_param_by_id(alloca_id.value)
            if param is None:
                self.updater.update(palloca_inst, "mload", [mem_loc], new_output=var)
            else:
                self.updater.update(palloca_inst, "assign", [param.func_var], new_output=var)
        else:
            # otherwise, it comes from memory, convert to an mload.
            self.updater.update(palloca_inst, "mload", [mem_loc], new_output=var)

        assert isinstance(mem_loc, IRAbstractMemLoc)
        size = mem_loc.size

        for inst in uses.copy():
            if inst.opcode == "mstore":
                if size <= 32:
                    self.updater.mk_assign(inst, inst.operands[0], new_output=var)
                else:
                    self.updater.update_operands(inst, {palloca_inst.output: mem_loc})
            elif inst.opcode == "mload":
                if size <= 32:
                    self.updater.mk_assign(inst, var)
                else:
                    self.updater.update_operands(inst, {palloca_inst.output: mem_loc})

    def _process_calloca(self, inst: IRInstruction):
        assert inst.opcode == "calloca"
        assert inst.output is not None
        assert len(inst.operands) == 2
        memloc = inst.operands[0]

        self.updater.mk_assign(inst, memloc)
