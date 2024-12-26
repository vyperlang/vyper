from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.fcg import FCGAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.passes.base_pass import IRPass


class FuncInlinerPass(IRPass):
    """
    This pass inlines functions into the call sites.
    """

    ctx: IRContext
    inline_count: int
    fcg: FCGAnalysis

    def run_pass(self):
        self.inline_count = 0
        self.ctx = self.function.ctx
        self.fcg = self.analyses_cache.request_analysis(FCGAnalysis)

        walk = self._build_call_walk()
        for func in walk:
            calls = self.fcg.get_calls(func)
            if len(calls) == 1 and False:
                # sys.stderr.write("**** Inlining function " + str(func.name) + "\n")
                self._inline_function(func, calls)
                self.ctx.remove_function(func)
                # break

        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(CFGAnalysis)

    def _build_call_walk(self):
        """
        DFS walk over the call graph.
        """
        visited = set()
        call_walk = []

        def dfs(fn):
            if fn in visited:
                return
            visited.add(fn)

            callees = self.fcg.get_callees(fn)
            for callee in callees:
                dfs(callee)

            call_walk.append(fn)

        dfs(self.function)

        return call_walk

    def _filter_candidates(self, func_call_counts):
        """
        Filter candidates for inlining. This will become more sophisticated in the future.
        """
        return [fn for fn, call_sites in func_call_counts.items() if len(call_sites) == 1]

    def _inline_function(self, func, call_sites):
        """
        Inline function into call sites.
        """
        for call_site in call_sites:
            self._inline_call_site(func, call_site)

    def _inline_call_site(self, func, call_site):
        """
        Inline function into call site.
        """
        prefix = f"inline_{self.inline_count}_"
        self.inline_count += 1
        call_site_bb = call_site.parent
        call_site_func = call_site_bb.parent

        call_site_return = IRBasicBlock(
            self.ctx.get_next_label(f"{prefix}inline_return"), call_site_bb.parent
        )
        call_idx = call_site_bb.instructions.index(call_site)

        for inst in call_site_bb.instructions[call_idx + 1 :]:
            call_site_return.insert_instruction(inst)
        call_site_func.append_basic_block(call_site_return)

        func_copy = func.copy(prefix)

        for bb in func_copy.get_basic_blocks():
            bb.parent = call_site_func
            call_site_func.append_basic_block(bb)
            for inst in bb.instructions:
                if inst.opcode == "param":
                    if inst.annotation == "return_buffer":
                        inst.opcode = "store"
                        inst.operands = [call_site.operands[1]]
                        inst.output = IRVariable(inst.output.name, inst.output.version + 1)
                    elif inst.annotation == "return_pc":
                        inst.make_nop()
                elif inst.opcode == "palloca":
                    inst.opcode = "store"
                    inst.operands = [inst.operands[0]]
                elif inst.opcode == "store":
                    if "ret_ofst" in inst.output.name or "ret_size" in inst.output.name:
                        inst.make_nop()
                elif inst.opcode == "ret":
                    inst.opcode = "jmp"
                    inst.operands = [call_site_return.label]
                elif inst.opcode in ["jmp", "jnz", "djmp", "phi"]:
                    for i, op in enumerate(inst.operands):
                        if isinstance(op, IRLabel):
                            inst.operands[i] = IRLabel(f"{prefix}{op.name}")

        call_site_bb.instructions = call_site_bb.instructions[:call_idx]
        call_site_bb.append_instruction("jmp", func_copy.entry.label)