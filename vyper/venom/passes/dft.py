from dataclasses import asdict, dataclass

from vyper.utils import OrderedSet
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass

_ALL = ("storage", "transient", "memory", "immutables")

writes = {
    "sstore": "storage",
    "tstore": "transient",
    "mstore": "memory",
    "istore": "immutables",
    "delegatecall": _ALL,
    "call": _ALL,
    "create": _ALL,
    "create2": _ALL,
    "invoke": _ALL,  # could be smarter, look up the effects of the invoked function
    "staticcall": "memory",
    "dloadbytes": "memory",
    "returndatacopy": "memory",
    "calldatacopy": "memory",
    "codecopy": "memory",
    "extcodecopy": "memory",
    "mcopy": "memory",
}
reads = {
    "sload": "storage",
    "tload": "transient",
    "iload": "immutables",
    "mstore": "memory",
    "mcopy": "memory",
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": _ALL,
    "log": "memory",
    "revert": "memory",
    "return": "memory",
    "sha3": "memory",
}


@dataclass
class Fence:
    storage: int = 0
    memory: int = 0
    transient: int = 0
    immutables: int = 0


def _compute_fence(opcode: str, fence: Fence) -> Fence:
    if opcode not in writes:
        return fence

    effects = get_writes(opcode)

    tmp = asdict(fence)
    for eff in effects:
        tmp[eff] += 1

    return Fence(**tmp)


def get_reads(opcode):
    ret = reads.get(opcode, ())
    if not isinstance(ret, tuple):
        ret = (ret,)
    return ret


def get_writes(opcode):
    ret = writes.get(opcode, ())
    if not isinstance(ret, tuple):
        ret = (ret,)
    return ret


def _intersect(tuple1, tuple2):
    ret = []
    for s in tuple1:
        if s in tuple2:
            ret.append(s)
    return tuple(ret)


def _can_reorder(inst1, inst2):
    if inst1.parent != inst2.parent:
        return False

    effects = _intersect(get_writes(inst1.opcode), get_writes(inst2.opcode))
    effects += _intersect(get_reads(inst2.opcode), get_writes(inst1.opcode))

    for eff in effects:
        if getattr(inst1.fence, eff) != getattr(inst2.fence, eff):  # type: ignore
            return False

    return True


class DFTPass(IRPass):
    function: IRFunction
    inst_order: dict[IRInstruction, int]
    inst_order_num: int
    fence: Fence

    def _process_instruction_r(self, bb: IRBasicBlock, inst: IRInstruction, offset: int = 0):
        for op in inst.get_outputs():
            assert isinstance(op, IRVariable), f"expected variable, got {op}"
            uses = self.dfg.get_uses(op)

            for uses_this in uses:
                if not _can_reorder(inst, uses_this):
                    continue

                # if the instruction is a terminator, we need to place
                # it at the end of the basic block
                # along with all the instructions that "lead" to it
                self._process_instruction_r(bb, uses_this, offset)

        if inst in self.visited_instructions:
            return
        self.visited_instructions.add(inst)
        self.inst_order_num += 1

        if inst.is_bb_terminator:
            offset = len(bb.instructions)

        if inst.opcode in ("phi", "param"):
            # phi and param instructions stay at the beginning of the basic
            # block and no input processing is needed
            self.inst_order[inst] = 0
            return

        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            assert target is not None, f"no producing instruction for {op}"
            if not _can_reorder(target, inst):
                continue

            self._process_instruction_r(bb, target, offset)

        self.inst_order[inst] = self.inst_order_num + offset

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        for inst in bb.instructions:
            inst.fence = self.fence  # type: ignore
            self.fence = _compute_fence(inst.opcode, self.fence)

        # We go throught the instructions and calculate the order in which they should be executed
        # based on the data flow graph. This order is stored in the inst_order dictionary.
        # We then sort the instructions based on this order.
        self.inst_order = {}
        self.inst_order_num = 0
        for inst in bb.instructions:
            self._process_instruction_r(bb, inst)

        bb.instructions.sort(key=lambda x: self.inst_order[x])

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)

        self.fence = Fence()
        self.visited_instructions: OrderedSet[IRInstruction] = OrderedSet()

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
