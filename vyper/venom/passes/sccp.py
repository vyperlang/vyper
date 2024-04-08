from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Union
from vyper.ir.optimizer import arith
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet, SizeLimits
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass


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

evm_ops = ["iszero", "signextend", "store"]


class SCCP(IRPass):
    ctx: IRFunction
    dom: DominatorTree
    uses: dict[IRVariable, IRBasicBlock]
    defs: dict[IRVariable, IRInstruction]
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
        self._propagate_constants()
        return 0

    def _calculate_sccp(self, entry: IRBasicBlock):
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
                        self._visitExpr(inst)

                if len(end.cfg_out) == 1:
                    self.work_list.append(FlowWorkItem(end, end.cfg_out.first()))
            elif isinstance(workItem, SSAWorkListItem):
                if workItem.inst.opcode == "phi":
                    self._visitPhi(workItem.inst)
                else:
                    self._visitExpr(workItem.inst)
                    # in_exec = [
                    #     workItem.basic_block in bb.cfg_in_exec for bb in workItem.basic_block.cfg_in
                    # ]
                    if len(workItem.basic_block.cfg_in_exec) > 0:
                        self._visitExpr(workItem.inst)

    def _propagate_constants(self):
        for bb in self.dom.dfs_walk:
            for inst in bb.instructions:
                self._replace_constants(inst, self.lattice)

    def _replace_constants(self, inst: IRInstruction, lattice: Lattice):
        # if inst.opcode == "phi":
        #     for phi_ops in inst.phi_operands:
        #         lat = lattice[phi_ops[0]]
        #         if isinstance(lat, IRLiteral):
            
        if inst.opcode == "jnz":
            lat = lattice[inst.operands[0]]
            if isinstance(lat, IRLiteral):
                if lat.value == 0:
                    target = inst.operands[2]
                else:
                    target = inst.operands[1]
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

        for i, op in enumerate(inst.operands):
            if isinstance(op, IRVariable):
                lat = lattice[op]
                if isinstance(lat, IRLiteral):
                    inst.operands[i] = lat

    def _visitPhi(self, inst: IRInstruction):
        assert inst.opcode == "phi", "Can't visit non phi instruction"
        vars = []
        for bb, var in inst.phi_operands:
            if bb not in inst.parent.cfg_in_exec:
                continue
            vars.append(self.lattice[var])
        value = reduce(_meet, vars, LatticeEnum.TOP)
        if value != self.lattice[inst.output]:
            self.lattice[inst.output] = value
            for use in self.uses[inst.output]:
                self.work_list.append(use)

    def _visitExpr(self, inst: IRInstruction):
        # print("Visit: ", inst.opcode)
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
                for op in inst.operands[1:]:
                    target = self.ctx.get_basic_block(op.name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
            else:
                if lat.value == 0:
                    target = self.ctx.get_basic_block(inst.operands[1].name)
                else:
                    target = self.ctx.get_basic_block(inst.operands[2].name)
                self.work_list.append(FlowWorkItem(inst.parent, target))
            # if _meet(lat, 0) == LatticeEnum.BOTTOM:
            #     target = self.ctx.get_basic_block(inst.operands[2].value)
            #     self.work_list.append(FlowWorkItem(inst.parent, target))
            # if _meet(lat, 1) == LatticeEnum.BOTTOM:
            #     target = self.ctx.get_basic_block(inst.operands[1].value)
            #     self.work_list.append(FlowWorkItem(inst.parent, target))
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
        elif opcode in arith or opcode in evm_ops:
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
        if opcode == "store":
            ret = ops[0]
        elif opcode == "iszero":
            ret = IRLiteral(1 if ops[0].value == 0 else 0)
        elif opcode == "signextend":
            ret = IRLiteral(_evm_signextend(ops))
        elif opcode in arith:
            fn = arith[opcode][0]
            ret = IRLiteral(fn(ops[0].value, ops[1].value) & SizeLimits.MAX_UINT256)
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
        for use in self.uses[inst.output]:
            self.work_list.append(SSAWorkListItem(use, use.parent))

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


def _evm_signextend(ops: list[IROperand]) -> int:
    bits = ops[0].value
    value = ops[1].value

    if bits > 31:
        return value

    bits = bits * 8 + 7
    sign_bit = 1 << bits
    if value & sign_bit:
        value |= SizeLimits.MAX_UINT256 - sign_bit
    else:
        value &= sign_bit - 1

    return value
