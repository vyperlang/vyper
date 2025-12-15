from vyper.exceptions import CompilerPanic
from vyper.utils import all2
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, LivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IROperand, IRVariable, IRLiteral
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class Mem2Var(IRPass):
    """
    This pass promoted memory operations to variable operations, when possible.
    It does yet do any memory aliasing analysis, so it is conservative.
    """

    function: IRFunction

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

        size, alloca_id = alloca_inst.operands
        var_name = self._mk_varname(var.value, alloca_id.value)
        var = IRVariable(var_name)
        uses = dfg.get_uses(alloca_inst.output)


        if any(inst.opcode == "add" for inst in uses):
            self._fix_adds(alloca_inst)
            return

        if not all2(inst.opcode in ["mstore", "mload", "return"] for inst in uses):
            return

        assert isinstance(size, IRLiteral)
        size = size.value

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
        size, alloca_id = palloca_inst.operands
        uses = dfg.get_uses(palloca_inst.output)

        if any(inst.opcode == "add" for inst in uses):
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
            self.updater.replace(palloca_inst, "mload", [size], new_output=var)
        else:
            self.updater.update(palloca_inst, "assign", [param.func_var], new_output=var)

        assert isinstance(size, IRLiteral)
        size = size.value

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

    def _process_calloca(self, inst: IRInstruction):
        assert inst.opcode == "calloca"
        assert len(inst.operands) == 3
        self._fix_adds(inst)

    def _fix_adds(self, mem_src: IRInstruction):
        uses = self.dfg.get_uses(mem_src.output)
        output = mem_src.output
        for inst in uses.copy():
            if inst.opcode != "add":
                continue
            other = [op for op in inst.operands if op != mem_src.output]
            assert len(other) == 1
            self.updater.update(inst, "gep", [output, other[0]])
            self._fix_adds(inst)
