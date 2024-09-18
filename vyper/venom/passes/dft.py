from collections import defaultdict
from dataclasses import asdict, dataclass

from vyper.utils import OrderedSet
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.liveness import LivenessAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass

_ALL = ("storage", "transient", "memory", "immutables", "balance", "returndata")

writes = {
    "sstore": "storage",
    "tstore": "transient",
    "mstore": "memory",
    "istore": "immutables",
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": "memory",
    "create": _ALL,
    "create2": _ALL,
    "invoke": _ALL,  # could be smarter, look up the effects of the invoked function
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
    "mload": "memory",
    "mcopy": "memory",
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": _ALL,
    "returndatasize": "returndata",
    "returndatacopy": "returndata",
    "balance": "balance",
    "selfbalance": "balance",
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
    balance: int = 0
    returndata: int = 0


# effects graph
class EffectsG:
    def __init__(self):
        self._graph = defaultdict(list)

        # not sure if this will be useful
        self._outputs = defaultdict(list)

    def analyze(self, bb):
        fence = Fence()

        read_groups = {}
        terms = {}

        for inst in bb.instructions:
            reads = _get_reads(inst.opcode)
            writes = _get_writes(inst.opcode)
            for eff in reads:
                fence_id = getattr(fence, eff)
                group = read_groups.setdefault((eff, fence_id), [])
                group.append(inst)

            # collect writes in a separate dict
            for eff in writes:
                fence_id = getattr(fence, eff)
                assert (eff, fence_id) not in terms
                terms[(eff, fence_id)] = inst

            fence = _compute_fence(inst.opcode, fence)

        for (effect, fence_id), write_inst in terms.items():
            reads = read_groups.get((effect, fence_id), [])
            for read in reads:
                if read == write_inst:
                    continue
                self._graph[write_inst].append(read)

            next_id = fence_id + 1

            next_write = terms.get((effect, next_id))
            if next_write is not None:
                self._graph[next_write].append(write_inst)

            next_reads = read_groups.get((effect, next_id), [])
            for inst in next_reads:
                self._graph[inst].append(write_inst)

        # invert the graph, go the other way
        for inst, dependencies in self._graph.items():
            # sanity check the graph
            assert inst not in dependencies, inst
            for target in dependencies:
                self._outputs[target].append(inst)

    def required_by(self, inst):
        return self._graph.get(inst, [])

    def downstream_of(self, inst):
        return self._outputs.get(inst, [])


def _get_reads(opcode):
    ret = reads.get(opcode, ())
    if not isinstance(ret, tuple):
        ret = (ret,)
    return ret


def _get_writes(opcode):
    ret = writes.get(opcode, ())
    if not isinstance(ret, tuple):
        ret = (ret,)
    return ret


def _compute_fence(opcode: str, fence: Fence) -> Fence:
    if opcode not in writes:
        return fence

    effects = _get_writes(opcode)

    tmp = asdict(fence)
    for eff in effects:
        tmp[eff] += 1

    return Fence(**tmp)


class DFTPass(IRPass):
    function: IRFunction

    def _process_instruction_r(self, bb: IRBasicBlock, inst: IRInstruction):
        if inst.parent != bb:
            return
        if inst in self.done:
            return

        for op in inst.get_outputs():
            assert isinstance(op, IRVariable), f"expected variable, got {op}"
            uses = self.dfg.get_uses(op)

            for use in reversed(uses):
                self._process_instruction_r(bb, use)

        if inst in self.started:
            return
        self.started.add(inst)

        if inst.opcode in ("phi", "param"):
            return

        for op in inst.get_input_variables():
            target = self.dfg.get_producing_instruction(op)
            assert target is not None, f"no producing instruction for {op}"
            self._process_instruction_r(bb, target)

        for target in self._effects_g.required_by(inst):
            self._process_instruction_r(bb, target)

        bb.instructions.append(inst)
        self.done.add(inst)

    def _process_basic_block(self, bb: IRBasicBlock) -> None:
        self._effects_g = EffectsG()
        self._effects_g.analyze(bb)

        instructions = bb.instructions.copy()
        bb.instructions = [inst for inst in bb.instructions if inst.opcode in ("phi", "param")]

        # start with out liveness
        if len(bb.cfg_out) > 0:
            next_bb = bb.cfg_out.first()
            target_stack = self.liveness.input_vars_from(bb, next_bb)
            for var in reversed(list(target_stack)):
                inst = self.dfg.get_producing_instruction(var)
                self._process_instruction_r(bb, inst)

        for inst in instructions:
            self._process_instruction_r(bb, inst)

        def key(inst):
            if inst.is_bb_terminator:
                return 2
            return 1

        bb.instructions.sort(key=key)

        # sanity check: the instructions we started with are the same
        # as we have now
        assert set(bb.instructions) == set(instructions), (instructions, bb)

    def run_pass(self) -> None:
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.liveness = self.analyses_cache.request_analysis(LivenessAnalysis)  # use out_vars

        self.started: OrderedSet[IRInstruction] = OrderedSet()
        self.done: OrderedSet[IRInstruction] = OrderedSet()

        for bb in self.function.get_basic_blocks():
            self._process_basic_block(bb)

        # for repr
        self.analyses_cache.force_analysis(LivenessAnalysis)
