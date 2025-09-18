from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Union

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
from vyper.venom.passes.sccp.eval import ARITHMETIC_OPS, eval_arith


class LatticeEnum(Enum):
    TOP = 1
    BOTTOM = 2


@dataclass
class SSAWorkListItem:
    inst: IRInstruction


@dataclass
class FlowWorkItem:
    start: IRBasicBlock
    end: IRBasicBlock


WorkListItem = Union[FlowWorkItem, SSAWorkListItem]
LatticeItem = Union[LatticeEnum, IRLiteral, IRLabel]
Lattice = dict[IRVariable, LatticeItem]


class SCCP(IRPass):
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

    cfg_dirty: bool

    def __init__(
        self, analyses_cache: IRAnalysesCache, function: IRFunction, /, remove_allocas=True
    ):
        super().__init__(analyses_cache, function)
        self.remove_allocas = remove_allocas

        self.lattice = {}
        self.work_list: list[WorkListItem] = []

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
        if work_item.inst.opcode == "phi":
            self._visit_phi(work_item.inst)
        elif len(self.cfg_in_exec[work_item.inst.parent]) > 0:
            self._visit_expr(work_item.inst)

    def _lookup_from_lattice(self, op: IROperand) -> LatticeItem:
        assert isinstance(op, IRVariable), f"Can't get lattice for non-variable ({op})"
        lat = self.lattice[op]
        assert lat is not None, f"Got undefined var {op}"
        return lat

    def _set_lattice(self, op: IROperand, value: LatticeItem):
        assert isinstance(op, IRVariable), f"Not a variable: {op}"
        self.lattice[op] = value

    def _eval_from_lattice(self, op: IROperand) -> LatticeItem:
        if isinstance(op, (IRLiteral, IRLabel)):
            return op

        assert isinstance(op, IRVariable), f"Not a variable: {op}"
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

        assert inst.output in self.lattice, "unreachable"  # sanity

        if value != self._lookup_from_lattice(inst.output):
            self._set_lattice(inst.output, value)
            self._add_ssa_work_items(inst)

    def _visit_expr(self, inst: IRInstruction):
        opcode = inst.opcode

        store_opcodes: tuple[str, ...] = ("assign",)
        if self.remove_allocas:
            store_opcodes += ("alloca", "palloca", "calloca")

        if opcode in store_opcodes:
            assert inst.output is not None, inst
            out = self._eval_from_lattice(inst.operands[0])
            self._set_lattice(inst.output, out)
            self._add_ssa_work_items(inst)
        elif opcode == "jmp":
            target = self.fn.get_basic_block(inst.operands[0].value)
            self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "jnz":
            lat = self._eval_from_lattice(inst.operands[0])

            if lat in (LatticeEnum.BOTTOM, LatticeEnum.TOP):
                for out_bb in self.cfg.cfg_out(inst.parent):
                    self.work_list.append(FlowWorkItem(inst.parent, out_bb))
            else:
                assert isinstance(lat, IRLiteral)  # sanity
                if lat.value == 0:
                    # jnz False branch
                    target = self.fn.get_basic_block(inst.operands[2].name)
                else:
                    # jnz True branch (any nonzero condition)
                    target = self.fn.get_basic_block(inst.operands[1].name)
                self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "djmp":
            lat = self._eval_from_lattice(inst.operands[0])
            if lat in (LatticeEnum.BOTTOM, LatticeEnum.TOP):
                for op in inst.operands[1:]:
                    target = self.fn.get_basic_block(op.name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
            elif isinstance(lat, IRLiteral):
                raise CompilerPanic("Unimplemented djmp with literal")
        elif opcode in ARITHMETIC_OPS:
            self._eval(inst)
        else:
            if inst.output is not None:
                self._set_lattice(inst.output, LatticeEnum.BOTTOM)
                self._add_ssa_work_items(inst)

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
        ops: list[IRLiteral] = []
        for op in inst.operands:
            # Evaluate the operand according to the lattice
            if isinstance(op, IRLabel):
                return finalize(LatticeEnum.BOTTOM)
            elif isinstance(op, IRVariable):
                eval_result = self.lattice[op]
            else:
                assert isinstance(op, IRLiteral)  # clarity
                eval_result = op

            # The value from the lattice should have evaluated to TOP,
            # BOTTOM, or a literal by now.

            # If any operand is BOTTOM, the whole operation is BOTTOM
            if eval_result is LatticeEnum.BOTTOM:
                return finalize(LatticeEnum.BOTTOM)
            # If any operand is TOP the operation is TOP
            if eval_result is LatticeEnum.TOP:
                return finalize(LatticeEnum.TOP)

            assert isinstance(eval_result, IRLiteral), (op, eval_result, inst.parent.label, inst)
            ops.append(eval_result)

        # If we haven't found BOTTOM yet, evaluate the operation
        assert all(isinstance(op, IRLiteral) for op in ops)
        res = IRLiteral(eval_arith(opcode, ops))
        return finalize(res)

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
            for inst in bb.instructions:
                self._replace_constants(inst)

    def _replace_constants(self, inst: IRInstruction):
        """
        This method replaces constant values in the instruction with
        their actual values. It also updates the instruction opcode in
        case of jumps and asserts as needed.
        """
        if inst.opcode == "jnz":
            lat = self._eval_from_lattice(inst.operands[0])

            if isinstance(lat, IRLiteral):
                if lat.value == 0:
                    target = inst.operands[2]
                else:
                    target = inst.operands[1]
                inst.opcode = "jmp"
                inst.operands = [target]

                self.cfg_dirty = True

        elif inst.opcode in ("assert", "assert_unreachable"):
            lat = self._eval_from_lattice(inst.operands[0])

            if isinstance(lat, IRLiteral):
                if lat.value > 0:
                    inst.make_nop()
                else:
                    raise StaticAssertionException(
                        f"assertion found to fail at compile time ({inst.error_msg}).",
                        inst.get_ast_source(),
                    )

        elif inst.opcode == "phi":
            return

        for i, op in enumerate(inst.operands):
            if isinstance(op, IRVariable):
                lat = self.lattice[op]
                if isinstance(lat, IRLiteral):
                    inst.operands[i] = lat


def _meet(x: LatticeItem, y: LatticeItem) -> LatticeItem:
    if x == LatticeEnum.TOP:
        return y
    if y == LatticeEnum.TOP or x == y:
        return x
    return LatticeEnum.BOTTOM
