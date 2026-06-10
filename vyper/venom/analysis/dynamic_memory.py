from __future__ import annotations

from dataclasses import dataclass

from vyper.venom.analysis.analysis import IRGlobalAnalysis
from vyper.venom.basicblock import IRLabel
from vyper.venom.call_layout import FunctionCallLayout, params_feed_fmp, parse_dret_shape
from vyper.venom.function import IRFunction

# FMP virtual-register opcodes (between DretDesugarPass and
# DallocaLoweringPass). A function containing any of these needs the FMP
# threaded; containing `retfmp` means it publishes its FMP to the caller.
_FMP_REGISTER_OPS = frozenset(["getfmp", "setfmp", "retfmp"])


@dataclass(frozen=True)
class DynamicMemoryInfo:
    has_dalloca: bool
    has_dret: bool
    has_fmp_ops: bool
    calls_need_fmp: bool
    needs_fmp: bool
    has_physical_hidden_fmp: bool
    returns_adopted_fmp: bool
    dret_shape: tuple[int, int] | None
    user_return_count: int | None


@dataclass(frozen=True)
class _DirectDynamicMemoryInfo:
    has_dalloca: bool
    has_dret: bool
    has_fmp_ops: bool
    has_physical_hidden_fmp: bool
    returns_adopted_fmp: bool
    dret_shape: tuple[int, int] | None
    user_return_count: int | None


class DynamicMemoryAnalysis(IRGlobalAnalysis):
    """
    Infer dynamic-memory calling-convention facts for each function.

    This intentionally keeps FMP facts out of IRFunction. The analysis tracks
    raw producer IR (`dalloca`/`dret`), the desugared FMP virtual-register
    form (`getfmp`/`setfmp`/`retfmp`) and lowered physical shapes, such as
    a hidden FMP param plus an adopted-FMP return value.
    """

    infos: dict[IRFunction, DynamicMemoryInfo]

    def analyze(self):
        functions = tuple(self.ctx.get_functions())
        direct = {fn: self._scan_direct(fn) for fn in functions}

        needs_fmp = {
            fn: (
                info.has_dalloca
                or info.has_dret
                or info.has_fmp_ops
                or info.has_physical_hidden_fmp
                or info.returns_adopted_fmp
            )
            for fn, info in direct.items()
        }

        changed = True
        while changed:
            changed = False
            for fn in functions:
                if not needs_fmp[fn] and any(
                    needs_fmp.get(callee, False) for callee in self._iter_callees(fn)
                ):
                    needs_fmp[fn] = True
                    changed = True

        self.infos = {}
        for fn, info in direct.items():
            calls_need_fmp = any(needs_fmp.get(callee, False) for callee in self._iter_callees(fn))
            self.infos[fn] = DynamicMemoryInfo(
                has_dalloca=info.has_dalloca,
                has_dret=info.has_dret,
                has_fmp_ops=info.has_fmp_ops,
                calls_need_fmp=calls_need_fmp,
                needs_fmp=needs_fmp[fn],
                has_physical_hidden_fmp=info.has_physical_hidden_fmp,
                returns_adopted_fmp=info.returns_adopted_fmp,
                dret_shape=info.dret_shape,
                user_return_count=info.user_return_count,
            )

    def get_info(self, fn: IRFunction) -> DynamicMemoryInfo:
        return self.infos.get(
            fn,
            DynamicMemoryInfo(
                has_dalloca=False,
                has_dret=False,
                has_fmp_ops=False,
                calls_need_fmp=False,
                needs_fmp=False,
                has_physical_hidden_fmp=False,
                returns_adopted_fmp=False,
                dret_shape=None,
                user_return_count=None,
            ),
        )

    def function_needs_fmp(self, fn: IRFunction) -> bool:
        return self.get_info(fn).needs_fmp

    def function_returns_adopted_fmp(self, fn: IRFunction) -> bool:
        return self.get_info(fn).returns_adopted_fmp

    def _iter_callees(self, fn: IRFunction):
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke" or len(inst.operands) == 0:
                    continue
                target = inst.operands[0]
                if not isinstance(target, IRLabel):
                    continue
                callee = fn.ctx.functions.get(target)
                if callee is not None:
                    yield callee

    def _scan_direct(self, fn: IRFunction) -> _DirectDynamicMemoryInfo:
        has_dalloca = False
        has_dret = False
        has_fmp_ops = False
        has_retfmp = False
        shapes: set[tuple[int, int]] = set()

        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "dalloca":
                    has_dalloca = True
                    continue
                if inst.opcode in _FMP_REGISTER_OPS:
                    has_fmp_ops = True
                    if inst.opcode == "retfmp":
                        has_retfmp = True
                    continue
                if inst.opcode == "dret":
                    has_dret = True
                    shape = parse_dret_shape(inst)
                    if shape is not None:
                        shapes.add(shape)

        dret_shape = next(iter(shapes)) if len(shapes) == 1 else None

        ret_arities = _ret_arities(fn)
        user_return_count = fn._return_value_count
        if user_return_count is None and dret_shape is not None:
            ordinary_count, dynamic_count = dret_shape
            user_return_count = ordinary_count + dynamic_count
        elif user_return_count is None and len(ret_arities) == 1:
            user_return_count = next(iter(ret_arities))

        has_physical_hidden_fmp = (
            FunctionCallLayout(fn).has_physical_hidden_fmp_param
            or self._has_entry_hidden_fmp_param(fn)
            or self._has_param_fmp_use(fn)
        )
        # the publish fact lives in the terminator opcode: `dret` (raw) and
        # `retfmp` (desugared) both make the caller adopt the callee's FMP.
        returns_adopted_fmp = dret_shape is not None or has_retfmp

        if (
            not returns_adopted_fmp
            and has_physical_hidden_fmp
            and user_return_count is not None
            and len(ret_arities) == 1
        ):
            returns_adopted_fmp = next(iter(ret_arities)) == user_return_count + 1

        return _DirectDynamicMemoryInfo(
            has_dalloca=has_dalloca,
            has_dret=has_dret,
            has_fmp_ops=has_fmp_ops,
            has_physical_hidden_fmp=has_physical_hidden_fmp,
            returns_adopted_fmp=returns_adopted_fmp,
            dret_shape=dret_shape,
            user_return_count=user_return_count,
        )

    def _has_entry_hidden_fmp_param(self, fn: IRFunction) -> bool:
        if fn is not self.ctx.entry_function or fn._invoke_param_count is not None:
            return False
        params = [inst for inst in fn.entry.instructions if inst.opcode == "param"]
        return len(params) == 1

    def _has_param_fmp_use(self, fn: IRFunction) -> bool:
        params = {inst.output for inst in fn.entry.instructions if inst.opcode == "param"}
        return params_feed_fmp(fn, params)


def _ret_arities(fn: IRFunction) -> set[int]:
    arities: set[int] = set()
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            # for both `ret` and `retfmp` the last operand is the return PC
            # and all preceding operands are (user-visible) return values
            if inst.opcode in ("ret", "retfmp"):
                arities.add(len(inst.operands) - 1)
    return arities
