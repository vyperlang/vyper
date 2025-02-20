from typing import List, Optional

from vyper.compiler.settings import OptimizationLevel
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis.cfg import CFGAnalysis
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.fcg import FCGAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.passes import FloatAllocas
from vyper.venom.passes.base_pass import IRGlobalPass


class FuncInlinerPass(IRGlobalPass):
    """
    This pass inlines functions into their call sites to reduce function call overhead.

    Limitations:
    - Does not handle recursive functions

    Side effects:
    - Modifies the control flow graph
    - Invalidates DFG, CFG and VarEquivalence analyses
    """

    _RETURN_BUFFER_ANNOTATION = "return_buffer"
    _RETURN_PC_ANNOTATION = "return_pc"
    _RETURN_OFFSET_MARKER = "ret_ofst"
    _RETURN_SIZE_MARKER = "ret_size"

    inline_count: int
    fcg: FCGAnalysis

    def run_pass(self):
        entry = self.ctx.entry_function
        self.inline_count = 0

        function_count = len(self.ctx.functions)
        self.fcg = self.analyses_caches[entry].request_analysis(FCGAnalysis)
        self.walk = self._build_call_walk(entry)

        for _ in range(function_count):
            candidate = self._select_inline_candidate()
            if candidate is None:
                return

            # print(f"Inlining function {candidate.name} with cost {candidate.code_size_cost}")

            calls = self.fcg.get_call_sites(candidate)
            self._inline_function(candidate, calls)
            self.ctx.remove_function(candidate)
            self.walk.remove(candidate)

            self.fcg = self.analyses_caches[entry].force_analysis(FCGAnalysis)

    def _select_inline_candidate(self) -> Optional[IRFunction]:
        for func in self.walk:
            call_count = len(self.fcg.get_call_sites(func))
            if call_count == 0:
                continue

            # Always inline if there is only one call site.
            if call_count == 1:
                return func

            # Decide whether to inline based on the optimization level.
            if self.settings.optimize == OptimizationLevel.CODESIZE:
                continue
            elif self.settings.optimize == OptimizationLevel.GAS:
                if func.code_size_cost <= 15:
                    return func
            elif self.settings.optimize == OptimizationLevel.NONE:
                continue
            else:
                raise CompilerPanic(
                    f"Unsupported inlining optimization level: {self.settings.optimize}"
                )

        return None

    def _inline_function(self, func: IRFunction, call_sites: List[IRInstruction]) -> None:
        """
        Inline function into call sites.
        """
        for call_site in call_sites:
            FloatAllocas(self.analyses_caches[func], func).run_pass()
            self._inline_call_site(func, call_site)
            fn = call_site.parent.parent
            self.analyses_caches[fn].invalidate_analysis(DFGAnalysis)
            self.analyses_caches[fn].invalidate_analysis(CFGAnalysis)

    def _inline_call_site(self, func: IRFunction, call_site: IRInstruction) -> None:
        """
        Inline function into call site.
        """
        # TODO: not allowed at all in Vyper at the moment
        #       but we could support it if we want to with Venom.
        #       (I think we should support tail call optimizable cases at least)
        # if func == call_site.parent.parent:
        #     raise CompilerPanic("Recursive function inlining is not supported")

        if call_site.opcode != "invoke":
            raise CompilerPanic(f"Expected invoke instruction, got {call_site.opcode}")

        prefix = f"il{self.inline_count}_"
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

        func_copy = self._clone_function(func, prefix)

        for bb in func_copy.get_basic_blocks():
            bb.parent = call_site_func
            call_site_func.append_basic_block(bb)
            param_idx = 0
            for inst in bb.instructions:
                if inst.opcode == "param":
                    inst.opcode = "store"
                    inst.operands = [call_site.operands[-param_idx - 1]]
                    inst.annotation = None
                    param_idx += 1

                elif inst.opcode == "palloca":
                    inst.opcode = "store"
                    inst.operands = [inst.operands[0]]
                elif inst.opcode == "ret":
                    inst.opcode = "jmp"
                    inst.operands = [call_site_return.label]
                elif inst.opcode in ["jmp", "jnz", "djmp", "phi"]:
                    for i, label in enumerate(inst.operands):
                        if isinstance(label, IRLabel) and func.has_basic_block(label.name):
                            inst.operands[i] = IRLabel(f"{prefix}{label.name}")
                elif inst.opcode == "revert":
                    bb.remove_instructions_after(inst)
                    bb.append_instruction("stop")
                    break

        call_site_bb.instructions = call_site_bb.instructions[:call_idx]
        call_site_bb.append_instruction("jmp", func_copy.entry.label)

    def _build_call_walk(self, function: IRFunction) -> OrderedSet[IRFunction]:
        """
        DFS walk over the call graph.
        """
        visited = set()
        call_walk = []

        def dfs(fn):
            if fn in visited:
                return
            visited.add(fn)

            called_functions = self.fcg.get_callees(fn)
            for func in called_functions:
                dfs(func)

            call_walk.append(fn)

        dfs(function)

        return OrderedSet(call_walk)

    def _clone_function(self, func: IRFunction, prefix: str) -> IRFunction:
        new_func_label = IRLabel(f"{prefix}{func.name.value}")
        clone = IRFunction(new_func_label)
        for bb in func.get_basic_blocks():
            clone.append_basic_block(self._clone_basic_block(bb, prefix))
        return clone

    def _clone_basic_block(self, bb: IRBasicBlock, prefix: str) -> IRBasicBlock:
        new_bb_label = IRLabel(f"{prefix}{bb.label.value}")
        new_bb = IRBasicBlock(new_bb_label, bb.parent)
        new_bb.instructions = [self._clone_instruction(inst, prefix) for inst in bb.instructions]
        for inst in new_bb.instructions:
            inst.parent = new_bb
        return new_bb

    def _clone_instruction(self, inst: IRInstruction, prefix: str) -> IRInstruction:
        ops: list[IROperand] = []
        for op in inst.operands:
            if isinstance(op, IRLabel):
                ops.append(IRLabel(op.value))
            elif isinstance(op, IRVariable):
                ops.append(IRVariable(f"{prefix}{op.name}"))
            else:
                ops.append(IRLiteral(op.value))

        output = None
        if inst.output:
            output = IRVariable(f"{prefix}{inst.output.name}")

        clone = IRInstruction(inst.opcode, ops, output)
        clone.parent = inst.parent
        clone.annotation = inst.annotation
        clone.ast_source = inst.ast_source
        clone.error_msg = inst.error_msg

        return clone
