from __future__ import annotations

from dataclasses import dataclass

from vyper.venom.basicblock import IRInstruction, IRLabel, IROperand, IRVariable
from vyper.venom.call_layout import FunctionCallLayout, InvokeLayout
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import memory_write_ops

from .analysis import IRGlobalAnalysis


@dataclass(frozen=True)
class _FnParamInfo:
    invoke_params: tuple[IRVariable, ...]


@dataclass(frozen=True)
class _ParamRoots:
    roots: frozenset[int]
    exclusive: bool


class MemoryParamRootResolver:
    """
    Resolve a pointer-like operand back to the user memory parameter indexes it derives from.

    This is shared by readonly-arg inference and copy-forwarding passes so
    "readonly internal param" means the same thing at every call site.
    All definitions are combined so the result also fails closed on pre-SSA
    variables with multiple reaching definitions.
    """

    def __init__(self, fn: IRFunction):
        invoke_param_insts = FunctionCallLayout(fn).user_params
        self.invoke_params = tuple(inst.output for inst in invoke_param_insts)
        self.invoke_param_index = {var: i for i, var in enumerate(self.invoke_params)}
        self.invoke_param_inst = {inst.output: inst for inst in invoke_param_insts}
        self.all_param_roots = frozenset(range(len(self.invoke_params)))
        self.definitions: dict[IRVariable, list[IRInstruction]] = {}
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                for output in inst.get_outputs():
                    self.definitions.setdefault(output, []).append(inst)

        self.memo: dict[IRVariable, _ParamRoots] = {}
        self.active: set[IRVariable] = set()

    def root_param_indices(self, op: IROperand) -> frozenset[int]:
        """
        Return every memory-param root that is known to reach `op`.

        This is a may-style query for mutability inference: unknown/non-param
        roots are ignored, because they do not identify a specific param to mark
        mutable.
        """
        if not isinstance(op, IRVariable):
            return frozenset()
        return self._resolve_var(op).roots

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
        result = self._resolve_var(op)
        return result.roots if result.exclusive else None

    def _resolve(self, op: IROperand) -> _ParamRoots:
        if not isinstance(op, IRVariable):
            return _ParamRoots(frozenset(), False)
        return self._resolve_var(op)

    def _resolve_var(self, var: IRVariable) -> _ParamRoots:
        if var in self.memo:
            return self.memo[var]
        if var in self.active:
            # def cycle: conservatively attribute every param root. this is a
            # may-query, so over-approximating marks more params mutable,
            # which is the safe direction. A cycle is never an exclusive alias.
            return _ParamRoots(self.all_param_roots, False)

        self.active.add(var)
        roots: set[int] = set()
        exclusive = True
        definitions = self.definitions.get(var, ())
        if len(definitions) == 0:
            exclusive = False
        for inst in definitions:
            result = self._resolve_inst(var, inst)
            roots.update(result.roots)
            exclusive &= result.exclusive
        self.active.remove(var)
        result = _ParamRoots(frozenset(roots), exclusive)
        self.memo[var] = result
        return result

    def _resolve_inst(self, var: IRVariable, inst: IRInstruction) -> _ParamRoots:
        param_inst = self.invoke_param_inst.get(var)
        if param_inst is inst:
            idx = self.invoke_param_index[var]
            return _ParamRoots(frozenset([idx]), True)

        op = inst.opcode
        if op == "assign":
            return self._resolve(inst.operands[0])

        if op in ("add", "sub"):
            arith_roots: set[int] = set()
            for operand in inst.operands:
                arith_roots.update(self._resolve(operand).roots)
            return _ParamRoots(frozenset(arith_roots), False)

        if op == "phi":
            phi_roots: set[int] = set()
            exclusive = True
            for _, operand in inst.phi_operands:
                result = self._resolve(operand)
                phi_roots.update(result.roots)
                exclusive &= result.exclusive
            return _ParamRoots(frozenset(phi_roots), exclusive)

        return _ParamRoots(frozenset(), False)


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
        root_resolver = MemoryParamRootResolver(fn)

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
