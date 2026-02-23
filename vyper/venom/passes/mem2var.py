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
    # FloatAllocas moves pallocas with memory initializations for params
    required_predecessors = ("MakeSSA", "FloatAllocas")
    required_successors = ("MakeSSA",)

    def run_pass(self):
        self.mem_alloc = self.function.ctx.mem_allocator
        self.analyses_cache.request_analysis(CFGAnalysis)
        dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(dfg)
        self.dfg = dfg

        self.var_name_count = 0
        for var, inst in dfg.outputs.copy().items():
            if inst.opcode == "alloca":
                self._process_alloca_var(dfg, inst, var)
            elif inst.opcode == "palloca":
                self._process_palloca_var(dfg, inst, var)
            elif inst.opcode == "calloca":
                self._process_calloca(inst)

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

        assert len(alloca_inst.operands) >= 1, (alloca_inst, alloca_inst.parent)

        size_lit = alloca_inst.operands[0]
        var_name = self._mk_varname(var.value)
        var = IRVariable(var_name)
        uses = dfg.get_uses(alloca_inst.output)

        if any(inst.opcode in ("add", "phi", "assign") for inst in uses):
            self._fix_adds(alloca_inst)
            return

        if not all2(inst.opcode in ["mstore", "mload", "return"] for inst in uses):
            return

        assert isinstance(size_lit, IRLiteral)
        size = size_lit.value

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

    def _process_palloca_var(self, dfg: DFGAnalysis, palloca_inst: IRInstruction, var: IRVariable):
        """
        Process alloca allocated variable. If it is only used by mstore/mload
        instructions, it is promoted to a stack variable. Otherwise, it is left as is.
        """
        size_lit, alloca_id = palloca_inst.operands
        # snapshot uses before any insertion - add_after mutates the live set
        uses = dfg.get_uses(palloca_inst.output).copy()

        if any(inst.opcode in ("add", "phi", "assign") for inst in uses):
            self._fix_adds(palloca_inst)
            return

        if not all2(inst.opcode in ["mstore", "mload"] for inst in uses):
            return

        # some value given to us by the calling convention
        fn = self.function

        # it comes as a stack parameter. this (reifying with param based
        # on alloca_id) is a bit kludgey, but we will live.
        param = fn.get_param_by_id(alloca_id.value)
        if param is None:
            # Memory-passed param: load the value from the palloca address.
            # Keep palloca (provides address), insert mload after it.
            inserted = self.updater.add_after(palloca_inst, "mload", [palloca_inst.output])
            assert inserted is not None  # help mypy
            var = inserted
        else:
            self.updater.update(palloca_inst, "assign", [param.func_var], new_output=var)

        assert isinstance(size_lit, IRLiteral)
        size = size_lit.value

        for inst in uses:
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

    def _process_calloca(self, inst: IRInstruction):
        assert inst.opcode == "calloca"
        assert len(inst.operands) == 3
        self._fix_adds(inst)

    def _fix_adds(self, mem_src: IRInstruction, _visited=None):
        if _visited is None:
            _visited = set()
        if mem_src in _visited:
            return
        _visited.add(mem_src)

        uses = self.dfg.get_uses(mem_src.output)
        output = mem_src.output
        for inst in uses.copy():
            if inst.opcode in ("phi", "assign"):
                self._fix_adds(inst, _visited)
                continue
            if inst.opcode != "add":
                continue
            other = [op for op in inst.operands if op != mem_src.output]
            assert len(other) == 1
            self.updater.update(inst, "gep", [output, other[0]])
            self._fix_adds(inst, _visited)
