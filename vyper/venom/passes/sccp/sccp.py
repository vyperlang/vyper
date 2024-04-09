from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Union
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet, SizeLimits
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.sccp.eval import ARITHMETIC_OPS


class LatticeEnum(Enum):
    TOP = 1
    BOTTOM = 2


@dataclass
class SSAWorkListItem:
    inst: IRInstruction
    basic_block: IRBasicBlock


@dataclass
class FlowWorkItem:
    start: IRBasicBlock
    end: IRBasicBlock


WorkListItem = Union[FlowWorkItem, SSAWorkListItem]
LatticeItem = Union[LatticeEnum, IRLiteral]
Lattice = dict[IRVariable, LatticeItem]


class SCCP(IRPass):
    ctx: IRFunction
    dom: DominatorTree
    uses: dict[IRVariable, IRInstruction]
    lattice: Lattice
    work_list: list[WorkListItem]
    cfg_dirty: bool

    def __init__(self, dom: DominatorTree):
        self.dom = dom
        self.lattice = {}
        self.work_list: list[WorkListItem] = []
        self.cfg_dirty = False

    def _run_pass(self, ctx: IRFunction, entry: IRBasicBlock) -> int:
        self.ctx = ctx
        self._compute_uses(self.dom)
        self._calculate_sccp(entry)
        # print("SCCP :", self.lattice)
        self._propagate_constants()
        self._propagate_variables()
        return 0

    def _propagate_variables(self):
        for bb in self.dom.dfs_walk:
            for inst in bb.instructions:
                if inst.opcode == "store":
                    uses = self.uses.get(inst.output, [])
                    remove_inst = True
                    for usage_inst in uses:
                        if usage_inst.opcode == "phi":
                            remove_inst = False
                            continue
                        for i, op in enumerate(usage_inst.operands):
                            if op == inst.output:
                                usage_inst.operands[i] = inst.operands[0]
                    if remove_inst:
                        inst.opcode = "nop"
                        inst.operands = []

    def _calculate_sccp(self, entry: IRBasicBlock):
        for bb in self.ctx.basic_blocks:
            bb.cfg_in_exec = OrderedSet()

        dummy = IRBasicBlock(IRLabel("__dummy_start"), self.ctx)
        self.work_list.append(FlowWorkItem(dummy, entry))

        for v in self.uses.keys():
            self.lattice[v] = LatticeEnum.TOP

        while len(self.work_list) > 0:
            workItem = self.work_list.pop()
            if isinstance(workItem, FlowWorkItem):
                start = workItem.start
                end = workItem.end
                if start in end.cfg_in_exec:
                    continue
                end.cfg_in_exec.add(start)

                for inst in end.instructions:
                    if inst.opcode == "phi":
                        self._visitPhi(inst)

                if len(end.cfg_in_exec) == 1:
                    for inst in end.instructions:
                        if inst.opcode == "phi":
                            continue
                        self._visitExpr(inst)

                if len(end.cfg_out) == 1:
                    self.work_list.append(FlowWorkItem(end, end.cfg_out.first()))
            elif isinstance(workItem, SSAWorkListItem):
                if workItem.inst.opcode == "phi":
                    self._visitPhi(workItem.inst)
                elif len(workItem.basic_block.cfg_in_exec) > 0:
                    self._visitExpr(workItem.inst)

    def _propagate_constants(self):
        for bb in self.dom.dfs_walk:
            for inst in bb.instructions:
                self._replace_constants(inst, self.lattice)

    def _replace_constants(self, inst: IRInstruction, lattice: Lattice):
        if inst.opcode == "jnz":
            lat = lattice[inst.operands[0]]
            if isinstance(lat, IRLiteral):
                if lat.value == 0:
                    target = inst.operands[1]
                else:
                    target = inst.operands[2]
                inst.opcode = "jmp"
                inst.operands = [target]
                self.cfg_dirty = True
        elif inst.opcode == "assert":
            lat = lattice[inst.operands[0]]
            if isinstance(lat, IRLiteral):
                if lat.value == 0:
                    inst.opcode = "nop"
                    inst.operands = []
                    self.cfg_dirty = True
        elif inst.opcode == "phi":
            return

        for i, op in enumerate(inst.operands):
            if isinstance(op, IRVariable):
                lat = lattice[op]
                if isinstance(lat, IRLiteral):
                    inst.operands[i] = lat

    def _visitPhi(self, inst: IRInstruction):
        assert inst.opcode == "phi", "Can't visit non phi instruction"
        vars = []
        for bb_label, var in inst.phi_operands:
            bb = self.ctx.get_basic_block(bb_label.name)
            if bb not in inst.parent.cfg_in_exec:
                continue
            vars.append(self.lattice[var])
        value = reduce(_meet, vars, LatticeEnum.TOP)
        if value != self.lattice[inst.output]:
            self.lattice[inst.output] = value
            for use in self.uses[inst.output]:
                self.work_list.append(SSAWorkListItem(use, use.parent))

    def _visitExpr(self, inst: IRInstruction):
        opcode = inst.opcode
        if opcode in ["store", "alloca"]:
            if isinstance(inst.operands[0], IRLiteral):
                self.lattice[inst.output] = inst.operands[0]
            else:
                self.lattice[inst.output] = self.lattice[inst.operands[0]]
            self._add_ssa_work_items(inst)
        elif opcode == "jmp":
            target = self.ctx.get_basic_block(inst.operands[0].value)
            self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "jnz":
            lat = self.lattice[inst.operands[0]]
            assert lat != LatticeEnum.TOP, f"Got undefined var at jmp at {inst.parent}"
            if lat == LatticeEnum.BOTTOM:
                for out_bb in inst.parent.cfg_out:
                    self.work_list.append(FlowWorkItem(inst.parent, out_bb))
            else:
                if lat.value == 0:
                    target = self.ctx.get_basic_block(inst.operands[1].name)
                else:
                    target = self.ctx.get_basic_block(inst.operands[2].name)
                self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "djmp":
            lat = self.lattice[inst.operands[0]]
            assert lat != LatticeEnum.TOP, f"Got undefined var at jmp at {inst.parent}"
            if lat == LatticeEnum.BOTTOM:
                for op in inst.operands[1:]:
                    target = self.ctx.get_basic_block(op.name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
            elif isinstance(lat, IRLiteral):
                assert False, "Implement me"

        elif opcode in ["param", "calldataload"]:
            self.lattice[inst.output] = LatticeEnum.BOTTOM
            self._add_ssa_work_items(inst)
        elif opcode == "mload":
            self.lattice[inst.output] = LatticeEnum.BOTTOM
        elif opcode in ARITHMETIC_OPS:
            self._eval(inst)
        else:
            self.lattice[inst.output] = LatticeEnum.BOTTOM

    def _eval(self, inst) -> LatticeItem:
        opcode = inst.opcode

        ops = []
        for op in inst.operands:
            if isinstance(op, IRVariable):
                ops.append(self.lattice[op])
            elif isinstance(op, IRLabel):
                return LatticeEnum.BOTTOM
            else:
                ops.append(op)

        if LatticeEnum.BOTTOM in ops:
            self.lattice[inst.output] = LatticeEnum.BOTTOM
            return LatticeEnum.BOTTOM

        ret = None
        if opcode in ARITHMETIC_OPS:
            fn = ARITHMETIC_OPS[opcode]
            ret = IRLiteral(fn(ops))
        elif len(ops) > 0:
            ret = ops[0]
        else:
            raise CompilerPanic("Bad constant evaluation")

        old_val = self.lattice.get(inst.output, LatticeEnum.TOP)
        if old_val != ret.value:
            self.lattice[inst.output] = ret
            self._add_ssa_work_items(inst)

        return ret

    def _add_ssa_work_items(self, inst: IRInstruction):
        if inst.output not in self.uses:
            self.uses[inst.output] = OrderedSet()

        for target_inst in self.uses[inst.output]:
            self.work_list.append(SSAWorkListItem(target_inst, target_inst.parent))

    def _compute_uses(self, dom: DominatorTree):
        self.uses = {}
        for bb in dom.dfs_walk:
            for var, insts in bb.get_uses().items():
                if var not in self.uses:
                    self.uses[var] = OrderedSet()
                self.uses[var].update(insts)


def _meet(x: LatticeItem, y: LatticeItem) -> LatticeItem:
    if x == LatticeEnum.TOP:
        return y
    if y == LatticeEnum.TOP or x == y:
        return x
    return LatticeEnum.BOTTOM
