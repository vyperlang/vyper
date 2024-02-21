from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.basicblock import (
    BB_TERMINATORS,
    CFG_ALTERING_INSTRUCTIONS,
    IRBasicBlock,
    IRInstruction,
    IRVariable,
)
from vyper.venom.function import IRFunction


def calculate_cfg(ctx: IRFunction) -> None:
    """
    Calculate (cfg) inputs for each basic block.
    """
    for bb in ctx.basic_blocks:
        bb.cfg_in = OrderedSet()
        bb.cfg_out = OrderedSet()
        bb.out_vars = OrderedSet()

    for bb in ctx.basic_blocks:
        assert len(bb.instructions) > 0, "Basic block should not be empty"
        last_inst = bb.instructions[-1]
        assert last_inst.opcode in BB_TERMINATORS, f"Last instruction should be a terminator {bb}"

        for inst in bb.instructions:
            if inst.opcode in CFG_ALTERING_INSTRUCTIONS:
                ops = inst.get_label_operands()
                for op in ops:
                    ctx.get_basic_block(op.value).add_cfg_in(bb)

    # Fill in the "out" set for each basic block
    for bb in ctx.basic_blocks:
        for in_bb in bb.cfg_in:
            in_bb.add_cfg_out(bb)


def _reset_liveness(ctx: IRFunction) -> None:
    for bb in ctx.basic_blocks:
        for inst in bb.instructions:
            inst.liveness = OrderedSet()


def _calculate_liveness(bb: IRBasicBlock) -> bool:
    """
    Compute liveness of each instruction in the basic block.
    Returns True if liveness changed
    """
    orig_liveness = bb.instructions[0].liveness.copy()
    liveness = bb.out_vars.copy()
    for instruction in reversed(bb.instructions):
        ops = instruction.get_inputs()

        for op in ops:
            if op in liveness:
                instruction.dup_requirements.add(op)

        liveness = liveness.union(OrderedSet.fromkeys(ops))
        out = instruction.get_outputs()[0] if len(instruction.get_outputs()) > 0 else None
        if out in liveness:
            liveness.remove(out)
        instruction.liveness = liveness

    return orig_liveness != bb.instructions[0].liveness


def _calculate_out_vars(bb: IRBasicBlock) -> bool:
    """
    Compute out_vars of basic block.
    Returns True if out_vars changed
    """
    out_vars = bb.out_vars.copy()
    for out_bb in bb.cfg_out:
        target_vars = input_vars_from(bb, out_bb)
        bb.out_vars = bb.out_vars.union(target_vars)
    return out_vars != bb.out_vars


def calculate_liveness(ctx: IRFunction) -> None:
    _reset_liveness(ctx)
    while True:
        changed = False
        for bb in ctx.basic_blocks:
            changed |= _calculate_out_vars(bb)
            changed |= _calculate_liveness(bb)

        if not changed:
            break


# calculate the input variables into self from source
def input_vars_from(source: IRBasicBlock, target: IRBasicBlock) -> OrderedSet[IRVariable]:
    liveness = target.instructions[0].liveness.copy()
    assert isinstance(liveness, OrderedSet)

    for inst in target.instructions:
        if inst.opcode == "phi":
            # we arbitrarily choose one of the arguments to be in the
            # live variables set (dependent on how we traversed into this
            # basic block). the argument will be replaced by the destination
            # operand during instruction selection.
            # for instance, `%56 = phi %label1 %12 %label2 %14`
            # will arbitrarily choose either %12 or %14 to be in the liveness
            # set, and then during instruction selection, after this instruction,
            # %12 will be replaced by %56 in the liveness set
            source1, source2 = inst.operands[0], inst.operands[2]
            phi1, phi2 = inst.operands[1], inst.operands[3]
            if source.label == source1:
                liveness.add(phi1)
                if phi2 in liveness:
                    liveness.remove(phi2)
            elif source.label == source2:
                liveness.add(phi2)
                if phi1 in liveness:
                    liveness.remove(phi1)
            else:
                # bad path into this phi node
                raise CompilerPanic(f"unreachable: {inst}")

    return liveness


# DataFlow Graph
# this could be refactored into its own file, but it's only used here
# for now
class DFG:
    _dfg_inputs: dict[IRVariable, list[IRInstruction]]
    _dfg_outputs: dict[IRVariable, IRInstruction]

    def __init__(self):
        self._dfg_inputs = dict()
        self._dfg_outputs = dict()

    # return uses of a given variable
    def get_uses(self, op: IRVariable) -> list[IRInstruction]:
        return self._dfg_inputs.get(op, [])

    # the instruction which produces this variable.
    def get_producing_instruction(self, op: IRVariable) -> IRInstruction:
        return self._dfg_outputs[op]

    @classmethod
    def build_dfg(cls, ctx: IRFunction) -> "DFG":
        dfg = cls()

        # Build DFG

        # %15 = add %13 %14
        # %16 = iszero %15
        # dfg_outputs of %15 is (%15 = add %13 %14)
        # dfg_inputs of %15 is all the instructions which *use* %15, ex. [(%16 = iszero %15), ...]
        for bb in ctx.basic_blocks:
            for inst in bb.instructions:
                operands = inst.get_inputs()
                res = inst.get_outputs()

                for op in operands:
                    inputs = dfg._dfg_inputs.setdefault(op, [])
                    inputs.append(inst)

                for op in res:  # type: ignore
                    dfg._dfg_outputs[op] = inst

        return dfg
