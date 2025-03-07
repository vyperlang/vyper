import pytest

from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.loop_detection import NaturalLoopDetectionAnalysis
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes import DFTPass
from vyper.venom.passes.loop_invariant_hosting import LoopInvariantHoisting


def _helper_reorder(fn: IRFunction):
    for bb in fn.get_basic_blocks():
        bb.instructions.sort(key=lambda inst: repr(inst))


def _create_loops(fn, depth, loop_id, body_fn=lambda _: (), top=True):
    bb = fn.get_basic_block()
    cond = IRBasicBlock(IRLabel(f"cond{loop_id}{depth}"), fn)
    body = IRBasicBlock(IRLabel(f"body{loop_id}{depth}"), fn)
    if top:
        exit_block = IRBasicBlock(IRLabel(f"exit_top{loop_id}{depth}"), fn)
    else:
        exit_block = IRBasicBlock(IRLabel(f"exit{loop_id}{depth}"), fn)
    fn.append_basic_block(cond)
    fn.append_basic_block(body)

    bb.append_instruction("jmp", cond.label)

    cond_var = IRVariable(f"cond_var{loop_id}{depth}")
    cond.append_instruction("iszero", 0, ret=cond_var)
    assert isinstance(cond_var, IRVariable)
    cond.append_instruction("jnz", cond_var, body.label, exit_block.label)
    body_fn(fn, loop_id, depth)
    if depth > 1:
        _create_loops(fn, depth - 1, loop_id, body_fn, top=False)
    bb = fn.get_basic_block()
    bb.append_instruction("jmp", cond.label)
    fn.append_basic_block(exit_block)


def _hoistable_body(loop_id, depth):
    return f"""
        %{loop_id}{depth} = 1
        %a0{loop_id}{depth} = add %{loop_id}{depth}, 1
        %a1{loop_id}{depth} = add %a0{loop_id}{depth}, %{loop_id}{depth}
        """


def _simple_body(loop_id, depth):
    return f"""
        %a{depth}{loop_id} = add 1, 2"""


def _create_loops_code(depth, loop_id, body=lambda _, _a: "", last: bool = False):
    if depth <= 0:
        return ""
    inner = _create_loops_code(depth - 1, loop_id, body, False)

    res = f"""
        jmp @cond{depth}{loop_id}
    cond{depth}{loop_id}:
        jnz %par, @exit{depth}{loop_id}, @body{depth}{loop_id}
    body{depth}{loop_id}:
        {body(loop_id, depth)}
    {inner}
        jmp @cond{depth}{loop_id}
    exit{depth}{loop_id}:
    """

    if last:
        res += """
        stop
        """

    return res


@pytest.mark.parametrize("depth", range(1, 4))
@pytest.mark.parametrize("count", range(1, 4))
def test_loop_detection_analysis(depth, count):
    loops = ""
    for i in range(count):
        loops += _create_loops_code(depth, i, _simple_body, last=(i == count - 1))

    code = f"""
    main:
        %par = param
    {loops}
    """

    print(code)

    ctx = parse_from_basic_block(code)
    assert len(ctx.functions) == 1

    fn = list(ctx.functions.values())[0]
    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(NaturalLoopDetectionAnalysis)
    assert isinstance(analysis, NaturalLoopDetectionAnalysis)

    assert len(analysis.loops) == depth * count


@pytest.mark.parametrize("depth", range(1, 4))
@pytest.mark.parametrize("count", range(1, 4))
def test_loop_invariant_hoisting_simple(depth, count):
    pre_loops = ""
    for i in range(count):
        pre_loops += _create_loops_code(depth, i, _simple_body, last=(i == count - 1))

    post_loops = ""
    for i in range(count):
        hoisted = ""
        for d in range(depth):
            hoisted += _simple_body(i, depth - d)
        post_loops += hoisted
        post_loops += _create_loops_code(depth, i, last=(i == count - 1))

    pre = f"""
    main:
        %par = param
    {pre_loops}
    """

    post = f"""
    main:
        %par = param
    {post_loops}
    """

    ctx = parse_from_basic_block(pre)
    print(ctx)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        LoopInvariantHoisting(ac, fn).run_pass()
        _helper_reorder(fn)

    post_ctx = parse_from_basic_block(post)

    for fn in post_ctx.functions.values():
        ac = IRAnalysesCache(fn)
        _helper_reorder(fn)

    print(ctx)
    print(post_ctx)

    assert_ctx_eq(ctx, post_ctx)


@pytest.mark.parametrize("depth", range(1, 4))
@pytest.mark.parametrize("count", range(1, 4))
def test_loop_invariant_hoisting_dependant(depth, count):
    pre_loops = ""
    for i in range(count):
        pre_loops += _create_loops_code(depth, i, _hoistable_body, last=(i == count - 1))

    post_loops = ""
    for i in range(count):
        hoisted = ""
        for d in range(depth):
            hoisted += _hoistable_body(i, depth - d)
        post_loops += hoisted
        post_loops += _create_loops_code(depth, i, last=(i == count - 1))

    pre = f"""
    main:
        %par = param
    {pre_loops}
    """

    post = f"""
    main:
        %par = param
    {post_loops}
    """

    ctx = parse_from_basic_block(pre)
    print(ctx)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        LoopInvariantHoisting(ac, fn).run_pass()
        _helper_reorder(fn)

    post_ctx = parse_from_basic_block(post)

    for fn in post_ctx.functions.values():
        _helper_reorder(fn)

    print(ctx)
    print(post_ctx)

    assert_ctx_eq(ctx, post_ctx)


def _unhoistable_body(loop_id, depth):
    return f"""
        %l{loop_id}{depth} = mload 64
        %a{loop_id}{depth} = add 2, %l{loop_id}{depth}
        mstore %a{loop_id}{depth}, 10
    """


@pytest.mark.parametrize("depth", range(1, 4))
@pytest.mark.parametrize("count", range(1, 4))
def test_loop_invariant_hoisting_unhoistable(depth, count):
    pre_loops = ""
    for i in range(count):
        pre_loops += _create_loops_code(depth, i, _unhoistable_body, last=(i == count - 1))

    pre = f"""
    main:
        %par = param
    {pre_loops}
    """

    ctx = parse_from_basic_block(pre)
    print(ctx)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        LoopInvariantHoisting(ac, fn).run_pass()

    print(ctx)

    orig = parse_from_basic_block(pre)

    assert_ctx_eq(ctx, orig)
