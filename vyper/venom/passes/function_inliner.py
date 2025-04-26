from typing import List, Optional

from vyper.compiler.settings import OptimizationLevel
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, FCGAnalysis, IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IROperand, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes import FloatAllocas
from vyper.venom.passes.base_pass import IRGlobalPass


class FunctionInlinerPass(IRGlobalPass):
    """
    This pass inlines functions into their call sites to reduce function call overhead.

    Limitations:
    - Does not handle recursive functions

    Side effects:
    - Modifies the control flow graph
    - Invalidates DFG and CFG
    """

    inline_count: int
    fcg: FCGAnalysis
    optimize: OptimizationLevel

    def __init__(
        self,
        analyses_caches: dict[IRFunction, IRAnalysesCache],
        ctx: IRContext,
        optimize: OptimizationLevel,
    ):
        super().__init__(analyses_caches, ctx)
        self.optimize = optimize

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

            # TODO: check if recomputing this is a perf issue or we should rather
            # update it in-place.
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
            if self.optimize == OptimizationLevel.CODESIZE:
                continue
            elif self.optimize == OptimizationLevel.GAS:
                if func.code_size_cost <= 15:
                    return func
            elif self.optimize == OptimizationLevel.NONE:
                continue
            else:  # pragma: nocover
                raise CompilerPanic(f"Unsupported inlining optimization level: {self.optimize}")

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

        prefix = f"inl{self.inline_count}_"
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
                    # NOTE: one of these params is the return pc. technically assigning
                    # a variable to a label (e.g. %1 = @label) as we are doing here is
                    # not valid venom code, but it will get removed in store elimination
                    # (or unused variable elimination)
                    inst.opcode = "store"
                    val = call_site.operands[-param_idx - 1]
                    inst.operands = [val]
                    param_idx += 1
                elif inst.opcode == "palloca":
                    inst.opcode = "store"
                    inst.operands = [inst.operands[0]]
                elif inst.opcode == "ret":
                    inst.opcode = "jmp"
                    inst.operands = [call_site_return.label]

            for inst in bb.instructions:
                if not inst.annotation:
                    inst.annotation = f"from {func.name}"

        call_site_bb.instructions = call_site_bb.instructions[:call_idx]
        call_site_bb.append_instruction("jmp", func_copy.entry.label)

    def _build_call_walk(self, function: IRFunction) -> OrderedSet[IRFunction]:
        """
        postorder DFS walk over the call graph.
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
        # clear the bb that is added by default
        # consider using func.copy() intead?
        clone._basic_block_dict.clear()
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
        func = inst.parent.parent
        ops: list[IROperand] = []
        for op in inst.operands:
            if isinstance(op, IRLabel):
                if func.has_basic_block(op.name):
                    # it is a valid label inside of this function
                    label = IRLabel(f"{prefix}{op.name}")
                else:
                    # otherwise it is something else (like a data label)
                    label = op
                ops.append(label)
            elif isinstance(op, IRVariable):
                ops.append(IRVariable(f"{prefix}{op.plain_name}"))
            else:
                ops.append(op)

        output = None
        if inst.output:
            output = IRVariable(f"{prefix}{inst.output.plain_name}")

        clone = IRInstruction(inst.opcode, ops, output)
        clone.parent = inst.parent
        clone.annotation = inst.annotation
        clone.ast_source = inst.ast_source
        clone.error_msg = inst.error_msg

        return clone
