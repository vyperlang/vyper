from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Union, Optional

from vyper.exceptions import CompilerPanic, StaticAssertionException
from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysesCache, LivenessAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.sccp.eval import ARITHMETIC_OPS

_inf = float("inf")


@dataclass
class Interval:
    min: Union[int, float]  # Use float for -inf, +inf
    max: Union[int, float]
    second_interval: Optional[tuple[Union[int, float], Union[int, float]]] = None

    def __init__(self, *args):
        if len(args) == 2:
            # Single range: [min, max]
            self.min = args[0] if args[0] == -_inf else int(args[0])
            self.max = args[1] if args[1] == _inf else int(args[1])
            self.second_interval = None
        elif len(args) == 4:
            # Disjoint range: [min1, max1] ∪ [min2, max2]
            self.min = args[0] if args[0] == -_inf else int(args[0])
            self.max = args[1] if args[1] == _inf else int(args[1])
            self.second_interval = (
                args[2] if args[2] == -_inf else int(args[2]),
                args[3] if args[3] == _inf else int(args[3])
            )
            assert self.max < self.second_interval[0], "Invalid disjoint range"
        else:
            raise ValueError("Interval must have 2 or 4 arguments")
        if len(args) == 2:
            assert self.min <= self.max, "Invalid interval"

    def __eq__(self, other):
        if not isinstance(other, Interval):
            return False
        if (self.second_interval is None) != (other.second_interval is None):
            return False
        if self.second_interval is not None:
            return (self.min == other.min and self.max == other.max and
                   self.second_interval == other.second_interval)
        return self.min == other.min and self.max == other.max

    def __repr__(self):
        if self.second_interval is not None:
            return f"[{self.min}, {self.max}] ∪ [{self.second_interval[0]}, {self.second_interval[1]}]"
        return f"[{self.min}, {self.max}]"

    def is_disjoint(self) -> bool:
        return self.second_interval is not None

    def contains_zero(self) -> bool:
        if self.is_disjoint():
            return (self.min <= 0 <= self.max) or (self.second_interval[0] <= 0 <= self.second_interval[1])
        return self.min <= 0 <= self.max

    def is_non_zero(self) -> bool:
        if self.is_disjoint():
            return True  # Disjoint ranges by definition exclude zero
        return self.min > 0 or self.max < 0


class LatticeEnum(Enum):
    TOP = 1


LatticeItem = Union[LatticeEnum, Interval]
Lattice = dict[IRVariable, LatticeItem]


@dataclass
class SSAWorkListItem:
    inst: IRInstruction


@dataclass
class FlowWorkItem:
    start: IRBasicBlock
    end: IRBasicBlock


WorkListItem = Union[FlowWorkItem, SSAWorkListItem]


class RangeValuePropagationPass(IRPass):
    """
    This class implements the Sparse Conditional Constant Propagation
    algorithm by Wegman and Zadeck. It is a forward dataflow analysis
    that propagates constant values through the IR graph. It is used
    to optimize the IR by removing dead code and replacing variables
    with their constant values.
    """

    fn: IRFunction
    dfg: DFGAnalysis
    cfg: CFGAnalysis
    lattice: Lattice
    work_list: list[WorkListItem]
    cfg_in_exec: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    branch_contexts: dict[IRBasicBlock, dict[IRVariable, Interval]]  # Track per-block overrides
    current_block: IRBasicBlock  # Track the current block being processed

    cfg_dirty: bool

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.lattice = {}
        self.work_list: list[WorkListItem] = []
        self.branch_contexts = {}
        self.current_block = None  # type: ignore

    def run_pass(self):
        self.fn = self.function
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.cfg_dirty = False

        self._calculate_sccp(self.fn.entry)
        self._propagate_constants()
        if self.cfg_dirty:
            self.analyses_cache.invalidate_analysis(CFGAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)
        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _calculate_sccp(self, entry: IRBasicBlock):
        """
        This method is the main entry point for the SCCP algorithm. It
        initializes the work list and the lattice and then iterates over
        the work list until it is empty. It then visits each basic block
        in the CFG and processes the instructions in the block.

        This method does not update the IR, it only updates the lattice
        and the work list. The `_propagate_constants()` method is responsible
        for updating the IR with the constant values.
        """
        self.cfg_in_exec = {bb: OrderedSet() for bb in self.fn.get_basic_blocks()}

        dummy = IRBasicBlock(IRLabel("__dummy_start"), self.fn)
        self.work_list.append(FlowWorkItem(dummy, entry))

        # Initialize the lattice with TOP values for all variables
        for v in self.dfg._dfg_outputs:
            self.lattice[v] = LatticeEnum.TOP

        # Iterate over the work list until it is empty
        # Items in the work list can be either FlowWorkItem or SSAWorkListItem
        while len(self.work_list) > 0:
            work_item = self.work_list.pop()
            if isinstance(work_item, FlowWorkItem):
                self._handle_flow_work_item(work_item)
            elif isinstance(work_item, SSAWorkListItem):
                self._handle_SSA_work_item(work_item)
            else:
                raise CompilerPanic("Invalid work item type")

    def _handle_flow_work_item(self, work_item: FlowWorkItem):
        """
        This method handles a FlowWorkItem.
        """
        start = work_item.start
        end = work_item.end
        if start in self.cfg_in_exec[end]:
            return
        self.cfg_in_exec[end].add(start)

        # Set the current block context
        self.current_block = end

        for inst in end.instructions:
            if inst.opcode == "phi":
                self._visit_phi(inst)
            else:
                # Stop at the first non-phi instruction
                # as phis are only valid at the beginning of a block
                break

        if len(self.cfg_in_exec[end]) == 1:
            for inst in end.instructions:
                if inst.opcode == "phi":
                    continue
                self._visit_expr(inst)

    def _handle_SSA_work_item(self, work_item: SSAWorkListItem):
        """
        This method handles a SSAWorkListItem.
        """
        # Set the current block context
        self.current_block = work_item.inst.parent

        if work_item.inst.opcode == "phi":
            self._visit_phi(work_item.inst)
        elif len(self.cfg_in_exec[work_item.inst.parent]) > 0:
            self._visit_expr(work_item.inst)

    def _lookup_from_lattice(self, op: IROperand) -> LatticeItem:
        assert isinstance(op, IRVariable), f"Can't get lattice for non-variable ({op})"
        overrides = self.branch_contexts.get(self.current_block)
        if overrides is not None:
            override = overrides.get(op)
            if override is not None:
                return override
        lat = self.lattice[op]
        assert lat is not None, f"Got undefined var {op}"
        return lat

    def _set_lattice(self, op: IROperand, value: LatticeItem):
        assert isinstance(op, IRVariable), f"Not a variable: {op}"
        self.lattice[op] = value

    def _eval_from_lattice(self, op: IROperand) -> LatticeItem:
        if isinstance(op, IRLiteral):
            return Interval(op.value, op.value)
        if isinstance(op, IRLabel):
            return Interval(-_inf, _inf)
        assert isinstance(op, IRVariable)
        return self._lookup_from_lattice(op)

    def _visit_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi", "Can't visit non phi instruction"
        in_vars: list[LatticeItem] = []
        for bb_label, var in inst.phi_operands:
            bb = self.fn.get_basic_block(bb_label.name)
            if bb not in self.cfg_in_exec[inst.parent]:
                continue
            in_vars.append(self._lookup_from_lattice(var))
        value = reduce(_meet, in_vars, LatticeEnum.TOP)  # type: ignore

        assert inst.output is not None  # sanity
        assert inst.output in self.lattice, "unreachable"
        if value != self.lattice[inst.output]:
            self.lattice[inst.output] = value
            self._add_ssa_work_items(inst)

    def _visit_expr(self, inst: IRInstruction):
        opcode = inst.opcode
        if opcode in ("store", "alloca", "palloca", "calloca"):
            assert inst.output is not None, inst
            out = self._eval_from_lattice(inst.operands[0])
            self._set_lattice(inst.output, out)
            self._add_ssa_work_items(inst)
        elif opcode == "jmp":
            target = self.fn.get_basic_block(inst.operands[0].value)
            self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "jnz":
            lat = self._eval_from_lattice(inst.operands[0])
            assert lat != LatticeEnum.TOP, f"Undefined var at jnz at {inst.parent}"
            if isinstance(lat, Interval):
                if lat.min > 0 or lat.max < 0:  # Always true (non-zero)
                    target = self.fn.get_basic_block(inst.operands[1].name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
                elif lat.min == 0 and lat.max == 0:  # Always false
                    target = self.fn.get_basic_block(inst.operands[2].name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
                else:
                    # Create contexts for both branches
                    true_target = self.fn.get_basic_block(inst.operands[1].name)
                    false_target = self.fn.get_basic_block(inst.operands[2].name)
                    
                    # For true branch, condition is non-zero
                    true_meet = Interval(-_inf, -1, 1, _inf)
                    
                    assert isinstance(inst.operands[0], IRVariable)
                    self.branch_contexts[true_target] = {inst.operands[0]: true_meet}
                    self.work_list.append(FlowWorkItem(inst.parent, true_target))
                    
                    # For false branch, condition is zero
                    false_meet = Interval(0, 0)
                    
                    self.branch_contexts[false_target] = {inst.operands[0]: false_meet}
                    self.work_list.append(FlowWorkItem(inst.parent, false_target))
        elif opcode == "djmp":
            lat = self._eval_from_lattice(inst.operands[0])
            assert lat != LatticeEnum.TOP
            return  # Leave as is for now
        elif opcode in ["param", "calldataload", "mload"]:
            assert isinstance(inst.output, IRVariable)
            self.lattice[inst.output] = Interval(-_inf, _inf)
            self._add_ssa_work_items(inst)
        elif opcode in ARITHMETIC_OPS:
            self._eval(inst)
        else:
            if inst.output is not None:
                self._set_lattice(inst.output, Interval(-_inf, _inf))

    def _apply_arithmetic(self, a: Interval, b: Interval, op: str) -> Interval:
        assert not (a.is_disjoint() and b.is_disjoint())

        def _union_interval(min1, max1, min2, max2) -> Interval:
            if min2 < min1:
                min1, max1, min2, max2 = min2, max2, min1, max1
            # Overlap or touch -> contiguous interval.
            if max1 >= min2:
                return Interval(min1, max(max1, max2))
            return Interval(min1, max1, min2, max2)

        if not (a.is_disjoint() or b.is_disjoint()):
            if op == "add":
                return Interval(a.min + b.min, a.max + b.max)
            if op == "sub":
                return Interval(a.min - b.max, a.max - b.min)
            raise ValueError(f"Unsupported operation: {op}")

        # at most one disjoint operand
        if op == "add":
            disjoint = a if a.is_disjoint() else b
            non_disjoint = b if a.is_disjoint() else a
            assert disjoint.second_interval is not None  # mypy
            min1 = disjoint.min + non_disjoint.min
            max1 = disjoint.max + non_disjoint.max
            min2 = disjoint.second_interval[0] + non_disjoint.min
            max2 = disjoint.second_interval[1] + non_disjoint.max
            return _union_interval(min1, max1, min2, max2)

        if op == "sub":
            if a.is_disjoint():
                # disjoint minuend
                disjoint = a
                non_disjoint = b
                assert disjoint.second_interval is not None  # mypy
                min1 = disjoint.min - non_disjoint.max
                max1 = disjoint.max - non_disjoint.min
                min2 = disjoint.second_interval[0] - non_disjoint.max
                max2 = disjoint.second_interval[1] - non_disjoint.min
                return _union_interval(min1, max1, min2, max2)

            # disjoint subtrahend
            disjoint = b
            non_disjoint = a
            assert disjoint.second_interval is not None  # mypy
            b1_min, b1_max = disjoint.min, disjoint.max
            b2_min, b2_max = disjoint.second_interval
            min1 = non_disjoint.min - b1_max
            max1 = non_disjoint.max - b1_min
            min2 = non_disjoint.min - b2_max
            max2 = non_disjoint.max - b2_min
            return _union_interval(min1, max1, min2, max2)

        raise ValueError(f"Unsupported operation: {op}")

    def _eval(self, inst) -> LatticeItem:
        """
        This method evaluates an arithmetic operation and returns the result.
        At the same time it updates the lattice with the result and adds the
        instruction to the SSA work list if the knowledge about the variable
        changed.
        """

        def finalize(ret):
            # Update the lattice if the value changed
            old_val = self.lattice.get(inst.output, LatticeEnum.TOP)
            if old_val != ret:
                self.lattice[inst.output] = ret
                self._add_ssa_work_items(inst)
            return ret

        opcode = inst.opcode
        if opcode not in ARITHMETIC_OPS:
            return finalize(Interval(-_inf, _inf))

        ops_intervals = []
        for op in inst.operands:
            if isinstance(op, IRLiteral):
                interval = Interval(op.value, op.value)
            elif isinstance(op, IRVariable):
                lat = self._eval_from_lattice(op)
                if lat == LatticeEnum.TOP:
                    return finalize(LatticeEnum.TOP)
                assert isinstance(lat, Interval)
                interval = lat
            else:  # e.g., IRLabel
                return finalize(Interval(-_inf, _inf))
            ops_intervals.append(interval)

        # Compute result based on opcode
        if opcode in ("add", "sub"):
            # For subtraction, the order is important: first operand - second operand
            return finalize(self._apply_arithmetic(ops_intervals[1], ops_intervals[0], opcode))
        # TODO: Add more instructions support
        else:
            return finalize(Interval(-_inf, _inf))

    def _add_ssa_work_items(self, inst: IRInstruction):
        for target_inst in self.dfg.get_uses(inst.output):  # type: ignore
            self.work_list.append(SSAWorkListItem(target_inst))

    def _propagate_constants(self):
        """
        This method iterates over the IR and replaces constant values
        with their actual values. It also replaces conditional jumps
        with unconditional jumps if the condition is a constant value.
        """
        for bb in self.function.get_basic_blocks():
            self.current_block = bb
            for inst in bb.instructions:
                self._replace_constants(inst)

    def _replace_constants(self, inst: IRInstruction):
        if inst.opcode == "jnz":
            lat = self._eval_from_lattice(inst.operands[0])
            if isinstance(lat, Interval):
                if lat.min > 0 or lat.max < 0:  # Always true
                    inst.opcode = "jmp"
                    inst.operands = [inst.operands[1]]
                    self.cfg_dirty = True
                elif lat.min == 0 and lat.max == 0:  # Always false
                    inst.opcode = "jmp"
                    inst.operands = [inst.operands[2]]
                    self.cfg_dirty = True
        elif inst.opcode in ("assert", "assert_unreachable"):
            lat = self._eval_from_lattice(inst.operands[0])
            if isinstance(lat, Interval):
                if lat.min == 0 and lat.max == 0:  # Always fails
                    raise StaticAssertionException(
                        f"assertion fails at compile time ({inst.error_msg}).",
                        inst.get_ast_source(),
                    )
                elif lat.min > 0 or lat.max < 0:  # Always true
                    inst.make_nop()
        elif inst.opcode == "phi":
            return

        for i, op in enumerate(inst.operands):
            if isinstance(op, IRVariable):
                lat = self._eval_from_lattice(op)
                if isinstance(lat, Interval) and lat.min == lat.max:
                    assert isinstance(lat.min, int)
                    inst.operands[i] = IRLiteral(lat.min)

    def _get_context(self, bb_label: str) -> "RangeValuePropagationPass":
        """Used in tests for introspection"""
        bb = self.fn.get_basic_block(bb_label)
        # Create a new pass instance with the block-specific overrides applied
        new_pass = RangeValuePropagationPass(self.analyses_cache, self.fn)
        new_pass.lattice = self.lattice.copy()
        overrides = self.branch_contexts.get(bb)
        if overrides is not None:
            new_pass.lattice.update(overrides)
        return new_pass

def _meet(x: LatticeItem, y: LatticeItem) -> LatticeItem:
    if x == LatticeEnum.TOP:
        return y
    if y == LatticeEnum.TOP:
        return x
    if isinstance(x, Interval) and isinstance(y, Interval):
        mins = [x.min, y.min]
        maxs = [x.max, y.max]
        if x.is_disjoint():
            assert x.second_interval is not None  # mypy
            mins.append(x.second_interval[0])
            maxs.append(x.second_interval[1])
        if y.is_disjoint():
            assert y.second_interval is not None  # mypy
            mins.append(y.second_interval[0])
            maxs.append(y.second_interval[1])
        return Interval(min(mins), max(maxs))
    raise CompilerPanic("Invalid lattice items for meet")
