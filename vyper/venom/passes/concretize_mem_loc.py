from collections import defaultdict

from vyper.utils import OrderedSet
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis
from vyper.venom.basicblock import (
    IRAbstractMemLoc,
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.memory_allocator import MemoryAllocator
from vyper.venom.passes.base_pass import IRPass


class ConcretizeMemLocPass(IRPass):
    allocated_in_bb: dict[IRBasicBlock, int]

    def run_pass(self, mem_allocator: MemoryAllocator):
        self.allocator = mem_allocator
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        mem_allocator.start_fn_allocation(self._get_used(mem_allocator))

        orig = mem_allocator.curr

        self.mem_liveness = MemLiveness(self.function, self.cfg, self.dfg)
        self.mem_liveness.analyze()

        livesets = list(self.mem_liveness.livesets.items())
        livesets.sort(key=lambda x: len(x[1]), reverse=False)

        for index, (mem, insts) in enumerate(livesets):
            curr = orig
            for i in range(index):
                before_mem, before_insts = livesets[i]
                if len(OrderedSet.intersection(insts, before_insts)) == 0:
                    continue
                place = mem_allocator.allocated[before_mem._id]
                curr = max(place[0] + place[1], curr)
            mem_allocator.curr = curr
            mem_allocator.get_place(mem)

        for bb in self.function.get_basic_blocks():
            self._handle_bb(bb)

        mem_allocator.end_fn_allocation(self.function)

    def _handle_bb(self, bb: IRBasicBlock):
        for inst in bb.instructions:
            if inst.opcode == "codecopyruntime":
                inst.opcode = "codecopy"
                continue
            new_ops = [self._handle_op(op) for op in inst.operands]
            inst.operands = new_ops
            if inst.opcode == "gep":
                inst.opcode = "add"
            elif inst.opcode == "mem_deploy_start":
                inst.opcode = "assign"

    def _handle_op(self, op: IROperand) -> IROperand:
        if isinstance(op, IRAbstractMemLoc) and op._id in self.allocator.allocated:
            return IRLiteral(self.allocator.allocated[op._id][0] + op.offset)
        elif isinstance(op, IRAbstractMemLoc):
            return IRLiteral(self.allocator.get_place(op) + op.offset)
        else:
            return op

    def _get_used(self, mem_alloc: MemoryAllocator) -> int:
        max_used = mem_alloc.curr
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "invoke":
                    continue

                callee_label = inst.operands[0]
                assert isinstance(callee_label, IRLabel)
                callee = self.function.ctx.get_function(callee_label)

                max_used = max(max_used, mem_alloc.function_mem_used[callee])

        return max_used


class MemLiveness:
    function: IRFunction
    cfg: CFGAnalysis

    liveat: dict[IRInstruction, OrderedSet[IRAbstractMemLoc]]
    livesets: dict[IRAbstractMemLoc, OrderedSet[IRInstruction]]

    def __init__(self, function: IRFunction, cfg: CFGAnalysis, dfg: DFGAnalysis):
        self.function = function
        self.cfg = cfg
        self.dfg = dfg
        self.liveat = defaultdict(OrderedSet)

    def analyze(self):
        while True:
            change = False
            for bb in self.cfg.dfs_post_walk:
                change |= self._handle_bb(bb)

            if not change:
                break

        self.livesets = defaultdict(OrderedSet)
        for inst, mems in self.liveat.items():
            for mem in mems:
                self.livesets[mem].add(inst)

    def _handle_bb(self, bb: IRBasicBlock) -> bool:
        curr: OrderedSet[IRAbstractMemLoc] = OrderedSet()
        if len(succs := self.cfg.cfg_out(bb)) > 0:
            for other in (self.liveat[succ.instructions[0]] for succ in succs):
                curr.update(other)

        before = self.liveat[bb.instructions[0]]

        for inst in reversed(bb.instructions):
            write_op = _get_memory_write_op(inst)
            write_ops = self._follow_op(write_op)
            read_op = _get_memory_read_op(inst)
            read_ops = self._follow_op(read_op)
            for write_op in write_ops:
                assert isinstance(write_op, IRAbstractMemLoc)
                size = _get_write_size(inst)
                if size is None:
                    continue
                if not isinstance(size, IRLiteral):
                    continue
                if write_op in curr and size == write_op.size:
                    curr.remove(write_op.no_offset())
            for read_op in read_ops:
                assert isinstance(read_op, IRAbstractMemLoc)
                curr.add(read_op.no_offset())
            self.liveat[inst] = curr.copy()

        if before != self.liveat[bb.instructions[0]]:
            return True

        return False

    def _follow_op(self, op: IROperand | None) -> set[IRAbstractMemLoc]:
        if op is None:
            return set()
        if isinstance(op, IRAbstractMemLoc):
            return {op}
        if not isinstance(op, IRVariable):
            return set()

        inst = self.dfg.get_producing_instruction(op)
        assert inst is not None
        if inst.opcode == "gep":
            mem = inst.operands[0]
            return self._follow_op(mem)
        elif inst.opcode == "phi":
            res = set()
            for _, var in inst.phi_operands:
                src = self._follow_op(var)
                res.update(src)
            return res
        return set()


def _get_memory_write_op(inst) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return dst
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        _, _, dst = inst.operands
        return dst
    elif opcode == "call":
        _, dst, _, _, _, _, _ = inst.operands
        return dst
    elif opcode in ("delegatecall", "staticcall"):
        _, dst, _, _, _, _ = inst.operands
        return dst
    elif opcode == "extcodecopy":
        _, _, dst, _ = inst.operands
        return dst

    return None


def _get_memory_read_op(inst) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mload":
        return inst.operands[0]
    elif opcode == "mcopy":
        _, src, _ = inst.operands
        return src
    elif opcode == "call":
        _, _, _, dst, _, _, _ = inst.operands
        return dst
    elif opcode in ("delegatecall", "staticcall"):
        _, _, _, dst, _, _ = inst.operands
        return dst
    elif opcode == "return":
        _, src = inst.operands
        return src
    elif opcode == "create":
        _, src, _value = inst.operands
        return src
    elif opcode == "create2":
        _salt, size, src, _value = inst.operands
        return src
    elif opcode == "sha3":
        _, offset = inst.operands
        return offset
    elif opcode == "log":
        _, src = inst.operands[-2:]
        return src
    elif opcode == "revert":
        size, src = inst.operands
        if size.value == 0:
            return None
        return src

    return None


def _get_write_size(inst: IRInstruction) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mstore":
        return IRLiteral(32)
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        size, _, _ = inst.operands
        return size
    elif opcode == "call":
        size, _, _, _, _, _, _ = inst.operands
        return size
    elif opcode in ("delegatecall", "staticcall"):
        size, _, _, _, _, _ = inst.operands
        return size
    elif opcode == "extcodecopy":
        size, _, _, _ = inst.operands
        return size

    return None
