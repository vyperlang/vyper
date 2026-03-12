from __future__ import annotations

from dataclasses import dataclass

from vyper.venom.analysis import DFGAnalysis
from vyper.venom.basicblock import IRInstruction, IRLabel, IROperand, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import memory_write_ops
from vyper.venom.passes.base_pass import IRGlobalPass


@dataclass(frozen=True)
class _FnParamInfo:
    # params that are passed via invoke operands (all params except return_pc)
    invoke_params: tuple[IRVariable, ...]
    # map param var -> invoke operand index
    invoke_param_index: dict[IRVariable, int]


class ReadonlyMemoryArgsAnalysisPass(IRGlobalPass):
    """
    Infer readonly invoke-arg positions from Venom IR.

    The result is stored on each IRFunction as:
      `_readonly_memory_invoke_arg_idxs: tuple[int, ...]`
    where indices are relative to invoke stack args (excluding label).

    Analysis is conservative and interprocedural:
    - local writes through a parameter-derived pointer mark it mutable
    - passing a parameter-derived pointer to a non-readonly callee arg marks it mutable
    - fixed-point iteration propagates mutability through the call graph
    """

    def run_pass(self):
        infos = {fn: self._collect_param_info(fn) for fn in self.ctx.get_functions()}

        readonly_by_fn: dict[IRFunction, tuple[bool, ...]] = {}
        for fn, info in infos.items():
            readonly_by_fn[fn] = tuple(True for _ in range(len(info.invoke_params)))

        changed = True
        while changed:
            changed = False
            for fn, info in infos.items():
                new_state = self._analyze_fn(fn, info, readonly_by_fn)
                if new_state != readonly_by_fn[fn]:
                    readonly_by_fn[fn] = new_state
                    changed = True

        for fn, state in readonly_by_fn.items():
            idxs = tuple(i for i, is_ro in enumerate(state) if is_ro)
            fn._readonly_memory_invoke_arg_idxs = idxs

    def _collect_param_info(self, fn: IRFunction) -> _FnParamInfo:
        params = [inst.output for inst in fn.entry.param_instructions]
        if len(params) == 0:
            return _FnParamInfo(tuple(), {})

        if fn._invoke_param_count is not None:
            # Structured metadata populated by codegen for internal functions.
            invoke_count = min(fn._invoke_param_count, len(params))
            invoke_params = tuple(params[:invoke_count])
        elif self._has_ret_instruction(fn):
            # Conservative fallback for test/manual IR that uses internal-call
            # convention but does not populate invoke metadata.
            invoke_params = tuple(params[:-1])
        else:
            # Entry/non-invoked functions have no return_pc operand in practice.
            invoke_params = tuple(params)

        invoke_param_index = {var: i for i, var in enumerate(invoke_params)}
        return _FnParamInfo(invoke_params, invoke_param_index)

    def _has_ret_instruction(self, fn: IRFunction) -> bool:
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "ret":
                    return True
        return False

    def _analyze_fn(
        self, fn: IRFunction, info: _FnParamInfo, readonly_by_fn: dict[IRFunction, tuple[bool, ...]]
    ) -> tuple[bool, ...]:
        n = len(info.invoke_params)
        if n == 0:
            return ()

        mutable = [False] * n
        dfg = self.analyses_caches[fn].request_analysis(DFGAnalysis)
        all_param_roots = frozenset(range(n))

        root_memo: dict[IRVariable, frozenset[int]] = {}
        root_active: set[IRVariable] = set()

        def root_param_indices(op: IROperand) -> frozenset[int]:
            if not isinstance(op, IRVariable):
                return frozenset()
            return root_param_indices_var(op)

        def root_param_indices_var(var: IRVariable) -> frozenset[int]:
            if var in root_memo:
                return root_memo[var]
            if var in root_active:
                # Cycles through phi/self-assign can arise in SSA-like IR.
                # Return "all params" here so we remain conservative for mutability.
                return all_param_roots

            idx = info.invoke_param_index.get(var, None)
            if idx is not None:
                roots = frozenset([idx])
                root_memo[var] = roots
                return roots

            root_active.add(var)
            inst = dfg.get_producing_instruction(var)
            roots = self._root_from_inst(inst, root_param_indices_var)
            root_active.remove(var)
            root_memo[var] = roots
            return roots

        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "invoke":
                    self._handle_invoke(inst, mutable, root_param_indices, readonly_by_fn)
                    continue

                write_ofst = memory_write_ops(inst).ofst
                if write_ofst is None:
                    continue

                for idx in root_param_indices(write_ofst):
                    mutable[idx] = True

        return tuple(not is_mut for is_mut in mutable)

    def _handle_invoke(
        self,
        inst: IRInstruction,
        mutable: list[bool],
        root_param_indices,
        readonly_by_fn: dict[IRFunction, tuple[bool, ...]],
    ) -> None:
        target = inst.operands[0]
        if not isinstance(target, IRLabel):
            # Conservative fallback for malformed/manual IR.
            for op in inst.operands[1:]:
                for idx in root_param_indices(op):
                    mutable[idx] = True
            return

        callee = self.ctx.functions.get(target, None)

        for op_idx, op in enumerate(inst.operands[1:], start=1):
            caller_idxs = root_param_indices(op)
            if len(caller_idxs) == 0:
                continue

            callee_arg_idx = op_idx - 1
            if callee is None:
                for caller_idx in caller_idxs:
                    mutable[caller_idx] = True
                continue

            callee_state = readonly_by_fn.get(callee, ())
            if callee_arg_idx >= len(callee_state) or not callee_state[callee_arg_idx]:
                for caller_idx in caller_idxs:
                    mutable[caller_idx] = True

    def _root_from_inst(self, inst: IRInstruction | None, root_param_indices_var) -> frozenset[int]:
        if inst is None:
            return frozenset()

        op = inst.opcode
        if op == "assign":
            src = inst.operands[0]
            if isinstance(src, IRVariable):
                return root_param_indices_var(src)
            return frozenset()

        if op == "gep":
            return self._root_from_gep(inst, root_param_indices_var)

        if op == "add":
            return self._root_from_add(inst, root_param_indices_var)

        if op == "sub":
            return self._root_from_sub(inst, root_param_indices_var)

        if op == "phi":
            roots: set[int] = set()
            for _, v in inst.phi_operands:
                roots.update(root_param_indices_var(v))
            return frozenset(roots)

        return frozenset()

    def _root_from_add(self, inst: IRInstruction, root_param_indices_var) -> frozenset[int]:
        roots: set[int] = set()
        for op in inst.operands:
            if not isinstance(op, IRVariable):
                continue
            roots.update(root_param_indices_var(op))
        return frozenset(roots)

    def _root_from_sub(self, inst: IRInstruction, root_param_indices_var) -> frozenset[int]:
        # IR order for sub(a, b) is [b, a].
        if len(inst.operands) != 2:
            return frozenset()
        b, a = inst.operands
        roots: set[int] = set()
        if isinstance(a, IRVariable):
            roots.update(root_param_indices_var(a))
        if isinstance(b, IRVariable):
            roots.update(root_param_indices_var(b))
        return frozenset(roots)

    def _root_from_gep(self, inst: IRInstruction, root_param_indices_var) -> frozenset[int]:
        # IR order for gep(ptr, offset) is [ptr, offset].
        if len(inst.operands) != 2:
            return frozenset()
        base, offset = inst.operands
        roots: set[int] = set()
        if isinstance(base, IRVariable):
            roots.update(root_param_indices_var(base))
        if isinstance(offset, IRVariable):
            roots.update(root_param_indices_var(offset))
        return frozenset(roots)
