from vyper.exceptions import CompilerPanic
from vyper.utils import all2
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class Mem2Var(IRPass):
    """
    This pass promoted memory operations to variable operations, when possible.
    It does yet do any memory aliasing analysis, so it is conservative.
    """

    function: IRFunction
    # Mem2Var is intentionally run in an SSA "sandwich".
    required_predecessors = ("MakeSSA",)
    required_successors = ("MakeSSA",)

    def run_pass(self):
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(dfg)

        self.var_name_count = 0
        for var, inst in dfg.outputs.copy().items():
            if inst.opcode == "alloca":
                self._process_alloca_var(dfg, inst, var)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _mk_varname(self, varname: str):
        varname = varname.removeprefix("%")
        varname = f"alloca_{varname}_{self.var_name_count}"
        self.var_name_count += 1
        return varname

    def _process_alloca_var(self, dfg: DFGAnalysis, alloca_inst: IRInstruction, var: IRVariable):
        """
        Process alloca allocated variable. If it is only used by
        mstore/mload/return instructions, it is promoted to a stack variable.
        Otherwise, it is left as is.
        """

        assert len(alloca_inst.operands) == 1, (alloca_inst, alloca_inst.parent)

        size_lit = alloca_inst.operands[0]
        uses = dfg.get_uses(alloca_inst.output)

        if not all2(inst.opcode in ["mstore", "mload", "return"] for inst in uses):
            return

        assert isinstance(size_lit, IRLiteral)
        size = size_lit.value
        var = IRVariable(self._mk_varname(var.value))

        # Check if there's at least one mstore (definition)
        has_mstore = any(inst.opcode == "mstore" for inst in uses)

        # If only uses are [return] or [mload, return] without mstore,
        # this alloca is never written to - skip promotion
        if not has_mstore:
            return

        for inst in uses.copy():
            if inst.opcode == "mstore":
                if size == 32:
                    self.updater.mk_assign(inst, inst.operands[0], new_output=var)
                elif size < 32:
                    raise CompilerPanic(
                        "Trying to write with mstore to memory smaller then 32 bytes"
                    )
            elif inst.opcode == "mload":
                if size == 32:
                    self.updater.mk_assign(inst, var)
                elif size < 32:
                    raise CompilerPanic("Trying to read with mload to memory smaller then 32 bytes")
            elif inst.opcode == "return":
                if size <= 32:
                    self.updater.add_before(inst, "mstore", [var, alloca_inst.output])
                inst.operands[1] = alloca_inst.output
