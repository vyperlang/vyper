from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from vyper.venom.basicblock import IRInstruction, IRLabel, IROperand, IRVariable
from vyper.venom.call_layout import FunctionCallLayout, InvokeLayout
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import memory_write_ops

from .analysis import IRGlobalAnalysis
from .dfg import DFGAnalysis


@dataclass(frozen=True)
class _FnParamInfo:
    invoke_params: tuple[IRVariable, ...]


class MemoryParamRootResolver:
    """
    Resolve a pointer-like operand back to the user memory parameter indexes it derives from.

    This is shared by readonly-arg inference and copy-forwarding passes so
    "readonly internal param" means the same thing at every call site.
    """

    def __init__(self, fn: IRFunction, dfg: DFGAnalysis, cycle_roots: frozenset[int] | None = None):
        self.dfg = dfg
        self.invoke_params = tuple(inst.output for inst in FunctionCallLayout(fn).user_params)
        self.invoke_param_index = {var: i for i, var in enumerate(self.invoke_params)}
        self.all_param_roots = frozenset(range(len(self.invoke_params)))
        self.cycle_roots = self.all_param_roots if cycle_roots is None else cycle_roots
        self.memo: dict[IRVariable, frozenset[int]] = {}
        self.exclusive_alias_memo: dict[IRVariable, frozenset[int] | None] = {}
        self.active: set[IRVariable] = set()
        self.exclusive_alias_active: set[IRVariable] = set()

    def root_param_indices(self, op: IROperand) -> frozenset[int]:
        """
        Return every memory-param root that is known to reach `op`.

        This is a may-style query for mutability inference: unknown/non-param
        roots are ignored, because they do not identify a specific param to mark
        mutable.
        """
        if not isinstance(op, IRVariable):
            return frozenset()
        return self._root_param_indices_var(op)

    def exclusive_param_alias_indices(self, op: IROperand) -> frozenset[int] | None:
        """
        Return param roots only if `op` is exactly param-backed.

        This intentionally follows only param, assign, and phi edges. Unlike
        `root_param_indices`, it does not treat pointer arithmetic as proof
        that the resulting value still points inside a param region, and it
        returns None when some path has an unknown/non-param root.
        """
        if not isinstance(op, IRVariable):
            return None
        return self._exclusive_param_alias_indices_var(op)

    def _root_param_indices_var(self, var: IRVariable) -> frozenset[int]:
        if var in self.memo:
            return self.memo[var]
        if var in self.active:
            return self.cycle_roots

        idx = self.invoke_param_index.get(var, None)
        if idx is not None:
            roots = frozenset([idx])
            self.memo[var] = roots
            return roots

        self.active.add(var)
        inst = self.dfg.get_producing_instruction(var)
        roots = self._root_from_inst(inst)
        self.active.remove(var)
        self.memo[var] = roots
        return roots

    def _root_from_inst(self, inst: IRInstruction | None) -> frozenset[int]:
        if inst is None:
            return frozenset()

        op = inst.opcode
        if op == "assign":
            src = inst.operands[0]
            return self.root_param_indices(src)

        if op == "add":
            return self._root_from_add(inst)

        if op == "sub":
            return self._root_from_sub(inst)

        if op == "phi":
            roots: set[int] = set()
            for _, v in inst.phi_operands:
                assert isinstance(v, IRVariable)
                roots.update(self._root_param_indices_var(v))
            return frozenset(roots)

        return frozenset()

    def _root_from_add(self, inst: IRInstruction) -> frozenset[int]:
        roots: set[int] = set()
        for op in inst.operands:
            roots.update(self.root_param_indices(op))
        return frozenset(roots)

    def _root_from_sub(self, inst: IRInstruction) -> frozenset[int]:
        if len(inst.operands) != 2:
            return frozenset()
        b, a = inst.operands
        roots: set[int] = set()
        roots.update(self.root_param_indices(a))
        roots.update(self.root_param_indices(b))
        return frozenset(roots)

    def _exclusive_param_alias_indices_var(self, var: IRVariable) -> frozenset[int] | None:
        if var in self.exclusive_alias_memo:
            return self.exclusive_alias_memo[var]
        if var in self.exclusive_alias_active:
            return None

        idx = self.invoke_param_index.get(var, None)
        if idx is not None:
            param_roots = frozenset([idx])
            self.exclusive_alias_memo[var] = param_roots
            return param_roots

        self.exclusive_alias_active.add(var)
        inst = self.dfg.get_producing_instruction(var)
        roots: frozenset[int] | None = self._exclusive_param_alias_from_inst(inst)
        self.exclusive_alias_active.remove(var)
        self.exclusive_alias_memo[var] = roots
        return roots

    def _exclusive_param_alias_from_inst(self, inst: IRInstruction | None) -> frozenset[int] | None:
        if inst is None:
            return None

        op = inst.opcode
        if op == "assign":
            return self.exclusive_param_alias_indices(inst.operands[0])

        if op == "phi":
            return self._combine_exclusive_param_aliases(var for _, var in inst.phi_operands)

        return None

    def _combine_exclusive_param_aliases(
        self, operands: Iterable[IROperand]
    ) -> frozenset[int] | None:
        roots: set[int] = set()
        for operand in operands:
            operand_roots = self.exclusive_param_alias_indices(operand)
            if operand_roots is None:
                return None
            roots.update(operand_roots)
        return frozenset(roots)


class ReadonlyMemoryArgsGlobalAnalysis(IRGlobalAnalysis):
    """
    Infer readonly invoke-arg positions from Venom IR.
    """

    readonly_idxs_by_fn: dict[IRFunction, tuple[int, ...]]

    def analyze(self):
        functions = tuple(self.ctx.get_functions())
        infos = {fn: self._collect_param_info(fn) for fn in functions}

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

        self.readonly_idxs_by_fn = {
            fn: tuple(i for i, is_ro in enumerate(state) if is_ro)
            for fn, state in readonly_by_fn.items()
        }

    def get_readonly_invoke_arg_idxs(self, fn: IRFunction) -> tuple[int, ...]:
        return self.readonly_idxs_by_fn.get(fn, ())

    def _collect_param_info(self, fn: IRFunction) -> _FnParamInfo:
        invoke_params = tuple(inst.output for inst in FunctionCallLayout(fn).user_params)
        return _FnParamInfo(invoke_params)

    def _analyze_fn(
        self, fn: IRFunction, info: _FnParamInfo, readonly_by_fn: dict[IRFunction, tuple[bool, ...]]
    ) -> tuple[bool, ...]:
        n = len(info.invoke_params)
        if n == 0:
            return ()

        mutable = [False] * n
        dfg = self.analyses_caches[fn].request_analysis(DFGAnalysis)
        root_resolver = MemoryParamRootResolver(fn, dfg)

        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "invoke":
                    self._handle_invoke(
                        inst, mutable, root_resolver.root_param_indices, readonly_by_fn
                    )
                    continue

                write_ofst = memory_write_ops(inst).ofst
                if write_ofst is None:
                    continue

                for idx in root_resolver.root_param_indices(write_ofst):
                    mutable[idx] = True

        return tuple(not is_mut for is_mut in mutable)

    def _handle_invoke(
        self,
        inst: IRInstruction,
        mutable: list[bool],
        root_param_indices,
        readonly_by_fn: dict[IRFunction, tuple[bool, ...]],
    ) -> None:
        layout = InvokeLayout(self.ctx, inst)
        target = layout.target
        if not isinstance(target, IRLabel):
            for op in layout.user_operands:
                for idx in root_param_indices(op):
                    mutable[idx] = True
            return

        callee = layout.callee

        for callee_arg_idx, op in enumerate(layout.user_operands):
            caller_idxs = root_param_indices(op)
            if len(caller_idxs) == 0:
                continue

            if callee is None:
                for caller_idx in caller_idxs:
                    mutable[caller_idx] = True
                continue

            callee_state = readonly_by_fn.get(callee, ())
            if callee_arg_idx >= len(callee_state) or not callee_state[callee_arg_idx]:
                for caller_idx in caller_idxs:
                    mutable[caller_idx] = True
