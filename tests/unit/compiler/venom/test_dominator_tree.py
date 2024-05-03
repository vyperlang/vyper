from typing import Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.dominators import DominatorTreeAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes.make_ssa import MakeSSA


def _add_bb(
    fn: IRFunction, label: IRLabel, cfg_outs: list[IRLabel], bb: Optional[IRBasicBlock] = None
) -> IRBasicBlock:
    bb = bb if bb is not None else IRBasicBlock(label, fn)
    fn.append_basic_block(bb)
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

    ctx = IRContext()
    fn = ctx.create_function(lab[1].value)

    fn.entry.append_instruction("jmp", lab[2])

    _add_bb(fn, lab[7], [])
    _add_bb(fn, lab[6], [lab[7], lab[2]])
    _add_bb(fn, lab[5], [lab[6], lab[3]])
    _add_bb(fn, lab[4], [lab[6]])
    _add_bb(fn, lab[3], [lab[5]])
    _add_bb(fn, lab[2], [lab[3], lab[4]])

    return fn


def test_deminator_frontier_calculation():
    fn = _make_test_ctx()
    bb1, bb2, bb3, bb4, bb5, bb6, bb7 = [fn.get_basic_block(str(i)) for i in range(1, 8)]

    ac = IRAnalysesCache(fn)
    dom = ac.request_analysis(DominatorTreeAnalysis)
    df = dom.dominator_frontiers

    assert len(df[bb1]) == 0, df[bb1]
    assert df[bb2] == OrderedSet({bb2}), df[bb2]
    assert df[bb3] == OrderedSet({bb3, bb6}), df[bb3]
    assert df[bb4] == OrderedSet({bb6}), df[bb4]
    assert df[bb5] == OrderedSet({bb3, bb6}), df[bb5]
    assert df[bb6] == OrderedSet({bb2}), df[bb6]
    assert len(df[bb7]) == 0, df[bb7]


def test_phi_placement():
    fn = _make_test_ctx()
    bb1, bb2, bb3, bb4, bb5, bb6, bb7 = [fn.get_basic_block(str(i)) for i in range(1, 8)]

    x = IRVariable("%x")
    bb1.insert_instruction(IRInstruction("mload", [IRLiteral(0)], x), 0)
    bb2.insert_instruction(IRInstruction("add", [x, IRLiteral(1)], x), 0)
    bb7.insert_instruction(IRInstruction("mstore", [x, IRLiteral(0)]), 0)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
