from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis import calculate_cfg
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.dominators import DominatorTree
from vyper.venom.function import IRFunction
from vyper.venom.passes.make_ssa import MakeSSA


def _add_bb(
    ctx: IRFunction, label: IRLabel, cfg_outs: [IRLabel], bb: Optional[IRBasicBlock] = None
) -> IRBasicBlock:
    bb = bb if bb is not None else IRBasicBlock(label, ctx)
    ctx.append_basic_block(bb)
    cfg_outs_len = len(cfg_outs)
    if cfg_outs_len == 0:
        bb.append_instruction("stop")
    elif cfg_outs_len == 1:
        bb.append_instruction("jmp", cfg_outs[0])
    elif cfg_outs_len == 2:
        bb.append_instruction("jnz", IRLiteral(1), cfg_outs[0], cfg_outs[1])
    else:
        raise CompilerPanic("Invalid number of CFG outs")
    return bb


def _make_test_ctx():
    lab = [IRLabel(str(i)) for i in range(0, 9)]

    ctx = IRFunction(lab[1])

    bb1 = ctx.basic_blocks[0]
    bb1.append_instruction("jmp", lab[2])

    _add_bb(ctx, lab[7], [])
    _add_bb(ctx, lab[6], [lab[7], lab[2]])
    _add_bb(ctx, lab[5], [lab[6], lab[3]])
    _add_bb(ctx, lab[4], [lab[6]])
    _add_bb(ctx, lab[3], [lab[5]])
    _add_bb(ctx, lab[2], [lab[3], lab[4]])

    return ctx


def test_deminator_frontier_calculation():
    ctx = _make_test_ctx()
    bb1, bb2, bb3, bb4, bb5, bb6, bb7 = [ctx.get_basic_block(str(i)) for i in range(1, 8)]

    calculate_cfg(ctx)
    dom = DominatorTree(ctx, bb1)

    assert len(dom.df[bb1]) == 0, dom.df[bb1]
    assert dom.df[bb2] == OrderedSet({bb2}), dom.df[bb2]
    assert dom.df[bb3] == OrderedSet({bb3, bb6}), dom.df[bb3]
    assert dom.df[bb4] == OrderedSet({bb6}), dom.df[bb4]
    assert dom.df[bb5] == OrderedSet({bb3, bb6}), dom.df[bb5]
    assert dom.df[bb6] == OrderedSet({bb2}), dom.df[bb6]
    assert len(dom.df[bb7]) == 0, dom.df[bb7]


def test_phi_placement():
    ctx = _make_test_ctx()
    bb1, bb2, bb3, bb4, bb5, bb6, bb7 = [ctx.get_basic_block(str(i)) for i in range(1, 8)]

    x = IRVariable("%x")
    bb1.insert_instruction(IRInstruction("mload", [IRLiteral(0)], x), 0)
    bb2.insert_instruction(IRInstruction("add", [x, IRLiteral(1)], x), 0)
    bb7.insert_instruction(IRInstruction("mstore", [x, IRLiteral(0)]), 0)

    MakeSSA.run_pass(ctx, bb1)


if __name__ == "__main__":
    test_phi_placement()
